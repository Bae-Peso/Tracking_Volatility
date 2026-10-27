"""n일전 예보 vs d0 정확도."""

import math
import unittest

from accu_weather import accuracy, codes
from tests.fakes import cfg

ACC = cfg()["accuracy"]


def forecast(lead, code=0, temp_max=20.0, temp_min=10.0, precip_mm=0.0, precip_prob=0, feel_max=None, feel_min=None):
    """체감온도를 안 주면 기온과 같다."""
    return {
        "target_date": "2026-11-01", "city_id": "c1", "source": "open-meteo", "lead_days": lead,
        "weather": codes.category(code), "weather_code": code,
        "temp_max": temp_max, "temp_min": temp_min, "precip_mm": precip_mm, "precip_prob": precip_prob,
        "feel_max": temp_max if feel_max is None else feel_max, "feel_min": temp_min if feel_min is None else feel_min,
    }


def slots(code_hours, prob_hours=None, base_code=3, base_prob=0):
    """1시간 슬롯 24개. code_hours: {코드: 시각들}, prob_hours: {확률: 시각들}. 나머지는 base."""
    code = {h: c for c, hours in code_hours.items() for h in hours}
    prob = {h: p for p, hours in (prob_hours or {}).items() for h in hours}
    return [{"slot": f"{h:02d}", "weather_code": code.get(h, base_code), "precip_prob": prob.get(h, base_prob)}
            for h in range(24)]


class AccuracyRowsTest(unittest.TestCase):
    def test_lead마다_한_줄_d0는_제외(self):
        rows = accuracy.accuracy_rows([forecast(n) for n in range(15)], ACC, "t")
        self.assertEqual([r["lead_days"] for r in rows], list(range(1, 15)))

    def test_d0와_같으면_100점(self):
        (r,) = accuracy.accuracy_rows([forecast(0), forecast(3)], ACC, "t")
        self.assertEqual(r["score"], 100.0)
        self.assertEqual(r["weather_match"], 1)
        self.assertEqual((r["temp_max_diff"], r["feel_max_diff"], r["precip_prob_diff"], r["weather_diff"]), (0, 0, 0, 0))

    def test_차이_계산과_점수(self):
        d0 = forecast(0, code=0, temp_max=20.0, temp_min=10.0, precip_mm=0.0, precip_prob=0)
        d5 = forecast(5, code=61, temp_max=22.0, temp_min=9.0, precip_mm=10.0, precip_prob=50)
        (r,) = accuracy.accuracy_rows([d0, d5], ACC, "t")
        self.assertEqual(r["weather_match"], 0)  # 맑음 vs 비
        self.assertEqual(r["temp_max_diff"], 2.0)  # 부호 유지: 높게 예보
        self.assertEqual(r["temp_min_diff"], -1.0)
        self.assertEqual(r["precip_prob_diff"], 50)
        self.assertAlmostEqual(r["precip_sqrt_diff"], math.sqrt(10.0))
        self.assertEqual((r["feel_max_diff"], r["feel_min_diff"]), (2.0, -1.0))
        self.assertAlmostEqual(r["weather_diff"], 0.35)  # 맑음 0 ↔ 약한 비 0.35
        # 기온·체감 (2+1)/2/5 = 0.3씩, 확률 0.5, 강수 1.0(최악), 날씨 0.35 → 100 × (1 − 0.2 × 2.45) = 51
        self.assertEqual(r["score"], 51.0)

    def test_같은_비라도_정도가_다르면_match는_1_차이는_반영(self):
        (r,) = accuracy.accuracy_rows([forecast(0, code=65), forecast(2, code=61)], ACC, "t")
        self.assertEqual(r["weather_match"], 1)
        self.assertAlmostEqual(r["weather_diff"], 0.45 - 0.35)

    def test_항목별_최악은_1로_자름(self):
        (r,) = accuracy.accuracy_rows([forecast(0, temp_max=0, temp_min=0),
                                       forecast(1, temp_max=30, temp_min=30, feel_max=0, feel_min=0)], ACC, "t")
        self.assertEqual(r["score"], 80.0)  # 기온만 최악 → 100 × (1 − 0.2)

    def test_기온이_같아도_체감온도가_다르면_감점(self):
        # 기온은 그대로인데 습도·바람 예보가 바뀌어 체감이 3℃씩 달라짐 → 체감 0.6 × 0.2
        (r,) = accuracy.accuracy_rows([forecast(0, feel_max=24.0, feel_min=6.0),
                                       forecast(4, feel_max=27.0, feel_min=3.0)], ACC, "t")
        self.assertEqual((r["temp_max_diff"], r["feel_max_diff"], r["feel_min_diff"]), (0, 3.0, -3.0))
        self.assertEqual(r["score"], 88.0)

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


class RainScaleTest(unittest.TestCase):
    """강수량은 제곱근 척도: 0 ↔ 10mm가 1. 적은 비의 시작은 크게, 많은 비 쪽 차이도 작아지지 않게."""

    def rain(self, d0_mm, f_mm):
        (r,) = accuracy.accuracy_rows([forecast(0, precip_mm=d0_mm), forecast(1, precip_mm=f_mm)], ACC, "t")
        return abs(r["precip_sqrt_diff"]) / math.sqrt(ACC["rain_worst_mm"])

    def test_예시(self):
        self.assertAlmostEqual(self.rain(0, 10), 1.0)
        self.assertAlmostEqual(self.rain(0, 1), 0.316, places=3)
        self.assertAlmostEqual(self.rain(10, 20), 0.414, places=3)
        self.assertAlmostEqual(self.rain(30, 50), 0.504, places=3)

    def test_0에서_1mm가_10에서_11mm보다_큼(self):
        self.assertGreater(self.rain(0, 1), 2 * self.rain(10, 11))


class HourlyTest(unittest.TestCase):
    """날씨·강수확률: 하루 대표값 차이(peak_share) + 3시간 묶음끼리 차이의 평균."""

    def rows(self, d0_slots, f_slots, d0=None, f=None):
        (r,) = accuracy.accuracy_rows([d0 or forecast(0, code=65), f or forecast(3, code=65)], ACC, "t",
                                      {0: d0_slots, 3: f_slots})
        return r

    def test_대표_날씨가_같아도_시간이_다르면_변동(self):
        # d0 강한 비 0~17시(6묶음) ↔ 3일전 0~2시(1묶음): 대표는 둘 다 65 → 대표 차이 0
        # 5묶음이 강한 비 0.45 ↔ 흐림 0.05 → 5 × 0.4 / 8 = 0.25, 반반이면 0.125
        r = self.rows(slots({65: range(18)}), slots({65: range(3)}))
        self.assertAlmostEqual(r["weather_diff"], 0.125)

    def test_평균이_같아도_시각이_바뀌면_변동(self):
        r = self.rows(slots({65: range(6, 12)}), slots({65: range(15, 21)}))
        self.assertAlmostEqual(r["weather_diff"], 0.5 * 4 * 0.4 / 8)

    def test_짧은_뇌우를_놓치면_대표값_차이가_남음(self):
        r = self.rows(slots({95: [14]}), slots({}), d0=forecast(0, code=95), f=forecast(3, code=3))
        self.assertAlmostEqual(r["weather_diff"], 0.5 * 0.7 + 0.5 * 0.7 / 8)

    def test_강수확률도_시간대별(self):
        # 하루 최대는 둘 다 80% → 대표 차이 0, 0~11시 ↔ 6~17시: 묶음 8개 중 4개가 80 ↔ 0 → 평균 40%p, 반반이면 20%p
        d0 = forecast(0, code=65, precip_prob=80)
        f = forecast(3, code=65, precip_prob=80)
        r = self.rows(slots({}, {80: range(12)}), slots({}, {80: range(6, 18)}), d0=d0, f=f)
        self.assertEqual(r["precip_prob_diff"], 0)
        self.assertAlmostEqual(r["precip_prob_hourly_diff"], 40.0)
        self.assertEqual(r["score"], 96.0)  # 확률 0.2 × 0.2 감점 (날씨 슬롯은 같음)

    def test_묶음_안에서_시각이_조금_어긋난_건_같다고_봄(self):
        r = self.rows(slots({65: [3, 4]}), slots({65: [4, 5]}))
        self.assertEqual(r["weather_diff"], 0)

    def test_슬롯이_없으면_대표값만(self):
        (r,) = accuracy.accuracy_rows([forecast(0, code=65), forecast(2, code=61)], ACC, "t")
        self.assertAlmostEqual(r["weather_diff"], 0.1)
        self.assertIsNone(r["precip_prob_hourly_diff"])


if __name__ == "__main__":
    unittest.main()
