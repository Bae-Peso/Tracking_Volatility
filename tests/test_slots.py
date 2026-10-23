"""1시간 값 → 슬롯, 슬롯 → 하루 통합."""

import unittest
from unittest import mock

from accu_weather.daily import day_rows
from accu_weather.sources import openmeteo
from tests.fakes import TODAY, hourly_data

FETCHED = "2026-10-23T13:00:00+00:00"


class ToSlotsTest(unittest.TestCase):
    def test_15일이면_360슬롯_lead_0부터_14(self):
        rows = openmeteo.to_slots(hourly_data(TODAY, 15), "c1", TODAY, FETCHED)
        self.assertEqual(len(rows), 360)
        self.assertEqual([r["slot"] for r in rows[:24]], [f"{h:02d}" for h in range(24)])
        self.assertEqual({r["lead_days"] for r in rows}, set(range(15)))
        self.assertEqual(rows[0]["target_date"], "2026-10-23")
        self.assertEqual(rows[-1]["target_date"], "2026-11-06")

    def test_1시간_슬롯은_받은_값_그대로(self):
        data = hourly_data(TODAY, 1)
        h = data["hourly"]
        h["temperature_2m"][1] = 9.5
        h["precipitation"][1] = 0.3
        h["weather_code"][1] = 61
        r = openmeteo.to_slots(data, "c1", TODAY, FETCHED)[1]
        self.assertEqual(r["slot"], "01")
        self.assertEqual((r["temp_max"], r["temp_min"], r["precip_mm"]), (9.5, 9.5, 0.3))
        self.assertEqual((r["weather_code"], r["weather"]), (61, 4))

    @mock.patch.object(openmeteo, "SLOT_HOURS", 3)
    def test_슬롯_묶는_규칙(self):
        data = hourly_data(TODAY, 1)
        h = data["hourly"]
        # 00~02시: 기온 5/9/7, 강수 0.5/1.0/0.25, 확률 10/40/20, 바람 3/8/1, 가시거리 9000/500/7000
        h["temperature_2m"][:3] = [5.0, 9.0, 7.0]
        h["precipitation"][:3] = [0.5, 1.0, 0.25]
        h["precipitation_probability"][:3] = [10, 40, 20]
        h["wind_speed_10m"][:3] = [3.0, 8.0, 1.0]
        h["visibility"][:3] = [9000.0, 500.0, 7000.0]
        h["weather_code"][:3] = [0, 61, 3]  # 가중치: 0 → 0, 61 → 1.0, 3 → 0.67
        r = openmeteo.to_slots(data, "c1", TODAY, FETCHED)[0]
        self.assertEqual((r["temp_max"], r["temp_min"]), (9.0, 5.0))
        self.assertEqual(r["precip_mm"], 1.75)
        self.assertEqual(r["precip_prob"], 40)
        self.assertEqual(r["wind_kmh"], 8.0)
        self.assertEqual(r["visibility_m"], 500.0)
        self.assertEqual(r["weather_code"], 61)  # 가중치가 가장 큰 코드
        self.assertEqual(r["weather"], 4)  # 비

    @mock.patch.object(openmeteo, "SLOT_HOURS", 3)
    def test_빈_값은_건너뜀(self):
        data = hourly_data(TODAY, 1)
        data["hourly"]["precipitation_probability"][:3] = [None, None, None]
        data["hourly"]["temperature_2m"][0] = None
        r = openmeteo.to_slots(data, "c1", TODAY, FETCHED)[0]
        self.assertIsNone(r["precip_prob"])
        self.assertEqual(r["temp_max"], 10.0)

    def test_lead는_수집일과의_날짜_차이(self):
        rows = openmeteo.to_slots(hourly_data(TODAY, 2), "c1", TODAY.replace(day=22), FETCHED)
        self.assertEqual({r["lead_days"] for r in rows}, {1, 2})


class DayRowsTest(unittest.TestCase):
    def test_하루_통합(self):
        data = hourly_data(TODAY, 2)
        h = data["hourly"]
        h["temperature_2m"][5] = 20.0  # 05시 최고
        h["temperature_2m"][22] = -1.0  # 22시 최저
        h["precipitation"][10:13] = [1.0, 2.0, 0.5]  # 10~12시
        h["weather_code"][13] = 95  # 13시 뇌우
        h["weather_code"][14] = 65  # 14시 강한 비 (가중치 3.0 < 뇌우 3.33)
        days = day_rows(openmeteo.to_slots(data, "c1", TODAY, FETCHED))
        self.assertEqual(len(days), 2)
        d0 = next(d for d in days if d["lead_days"] == 0)
        self.assertEqual(d0["slot"], "day")
        self.assertEqual((d0["temp_max"], d0["temp_min"]), (20.0, -1.0))
        self.assertEqual(d0["precip_mm"], 3.5)
        self.assertEqual(d0["weather_code"], 95)
        self.assertEqual(d0["weather"], 6)
        self.assertEqual(d0["fetched_at"], FETCHED)


if __name__ == "__main__":
    unittest.main()
