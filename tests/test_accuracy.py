"""n일전 예보 vs d0 정확도."""

import math
import unittest

from accu_weather import accuracy, codes
from tests.fakes import cfg

ACC = cfg()["accuracy"]


def forecast(lead, code=0, temp_max=20.0, temp_min=10.0, precip_mm=0.0, precip_prob=0):
    return {
        "target_date": "2026-11-01", "city_id": "c1", "source": "open-meteo", "lead_days": lead,
        "weather": codes.category(code), "weather_code": code,
        "temp_max": temp_max, "temp_min": temp_min, "precip_mm": precip_mm, "precip_prob": precip_prob,
    }


class AccuracyRowsTest(unittest.TestCase):
    def test_lead마다_한_줄_d0는_제외(self):
        rows = accuracy.accuracy_rows([forecast(n) for n in range(15)], ACC, "t")
        self.assertEqual([r["lead_days"] for r in rows], list(range(1, 15)))

    def test_d0와_같으면_100점(self):
        (r,) = accuracy.accuracy_rows([forecast(0), forecast(3)], ACC, "t")
        self.assertEqual(r["score"], 100.0)
        self.assertEqual(r["weather_match"], 1)
        self.assertEqual((r["temp_max_diff"], r["precip_prob_diff"], r["weather_severity"]), (0, 0, 0))

    def test_차이_계산과_점수(self):
        d0 = forecast(0, code=0, temp_max=20.0, temp_min=10.0, precip_mm=0.0, precip_prob=0)
        d5 = forecast(5, code=61, temp_max=22.0, temp_min=9.0, precip_mm=10.0, precip_prob=50)
        (r,) = accuracy.accuracy_rows([d0, d5], ACC, "t")
        self.assertEqual(r["weather_match"], 0)  # 맑음 vs 비
        self.assertEqual(r["temp_max_diff"], 2.0)  # 부호 유지: 높게 예보
        self.assertEqual(r["temp_min_diff"], -1.0)
        self.assertEqual(r["precip_prob_diff"], 50)
        self.assertAlmostEqual(r["precip_log_diff"], math.log1p(10.0))
        self.assertAlmostEqual(r["weather_severity"], 1.0 / 5)  # 가중치 1.0 차이
        # 온도 (2+1)/2/5 = 0.3, 확률 0.5, 강수 1.0(최악), 날씨 0.2 → 100 × (1 − 0.25 × 2.0) = 50
        self.assertEqual(r["score"], 50.0)

    def test_같은_비라도_정도가_다르면_match는_1_severity는_반영(self):
        (r,) = accuracy.accuracy_rows([forecast(0, code=65), forecast(2, code=61)], ACC, "t")
        self.assertEqual(r["weather_match"], 1)
        self.assertAlmostEqual(r["weather_severity"], (3.0 - 1.0) / 5)

    def test_항목별_최악은_1로_자름(self):
        (r,) = accuracy.accuracy_rows([forecast(0, temp_max=0, temp_min=0),
                                       forecast(1, temp_max=30, temp_min=30)], ACC, "t")
        self.assertEqual(r["score"], 75.0)  # 온도만 최악 → 100 × (1 − 0.25)

    def test_d0가_없으면_계산_안_함(self):
        self.assertEqual(accuracy.accuracy_rows([forecast(1), forecast(2)], ACC, "t"), [])

    def test_빠진_lead는_그_줄만_없음(self):
        rows = accuracy.accuracy_rows([forecast(0), forecast(1), forecast(7)], ACC, "t")
        self.assertEqual([r["lead_days"] for r in rows], [1, 7])

    def test_값이_빠지면_점수는_None(self):
        (r,) = accuracy.accuracy_rows([forecast(0), forecast(1, precip_prob=None)], ACC, "t")
        self.assertIsNone(r["precip_prob_diff"])
        self.assertIsNone(r["score"])
        self.assertEqual(r["temp_max_diff"], 0)


if __name__ == "__main__":
    unittest.main()
