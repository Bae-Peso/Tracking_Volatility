"""도시별 현지 22시 판단, 수집 → 저장 → 정확도, 실패 기록."""

import copy
import sqlite3
import tempfile
import unittest
import urllib.error
from datetime import timedelta, timezone
from pathlib import Path
from unittest import mock

from accu_weather import accuracy, collect, db
from accu_weather.daily import day_rows
from accu_weather.sources import openmeteo
from tests.fakes import TODAY, TempDB, add_osaka, cfg, hourly_data, local

TOKYO_22 = {"Asia/Tokyo": local("Asia/Tokyo", 2026, 10, 23, 22, 0)}


def fake_clock(times):
    """{timezone: datetime} 로 도시 현지 시각과 fetched_at(UTC)을 고정한다."""
    now = next(iter(times.values()))
    return (mock.patch.object(collect, "_now_local", lambda c: times[c["timezone"]]),
            mock.patch.object(db, "utc_now", lambda: now.astimezone(timezone.utc).isoformat(timespec="seconds")))


def fake_fetch(start):
    """start 날짜부터 15일치를 도시 수만큼 돌려주는 가짜 fetch."""
    return mock.patch.object(openmeteo, "fetch", lambda cities, n: [hourly_data(start, n) for _ in cities])


def run_at(conn, times, start=TODAY, **kwargs):
    clock, utc = fake_clock(times)
    with clock, utc, fake_fetch(start), mock.patch("builtins.print"):
        collect.run(conn, cfg(), **kwargs)


class DueCitiesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TempDB()
        self.conn = self.tmp.__enter__()
        self.osaka = add_osaka(self.conn)
        db.add_city(self.conn, "New York", "United States", 40.71, -74.01, "America/New_York")
        self.cities = db.list_cities(self.conn, active_only=True)

    def tearDown(self):
        self.tmp.__exit__()

    def due(self, tokyo, new_york):
        clock, _ = fake_clock({"Asia/Tokyo": local("Asia/Tokyo", *tokyo),
                               "America/New_York": local("America/New_York", *new_york)})
        with clock:
            return [c["name"] for c in collect.due_cities(self.conn, self.cities, 22)]

    def fetch_osaka_at(self, *tokyo):
        run_at(self.conn, {"Asia/Tokyo": local("Asia/Tokyo", *tokyo)}, force=True, city_ids=[self.osaka])

    def test_22시_전에는_안_받음(self):
        self.assertEqual(self.due((2026, 10, 23, 21, 30), (2026, 10, 23, 8, 30)), [])

    def test_현지_22시가_되면_그_도시만(self):
        self.assertEqual(self.due((2026, 10, 23, 22, 0), (2026, 10, 23, 9, 0)), ["Osaka"])
        self.assertEqual(self.due((2026, 10, 24, 11, 0), (2026, 10, 23, 22, 0)), ["New York"])

    def test_22시_이후_받았으면_건너뜀(self):
        self.fetch_osaka_at(2026, 10, 23, 22, 0, 5)
        self.assertEqual(self.due((2026, 10, 23, 22, 30), (2026, 10, 23, 9, 30)), [])
        self.assertEqual(self.due((2026, 10, 24, 22, 0), (2026, 10, 24, 9, 0)), ["Osaka"])  # 다음 날

    def test_22시_전_수동_수집은_22시_수집을_막지_않음(self):
        self.fetch_osaka_at(2026, 10, 23, 20, 29)
        self.assertEqual(self.due((2026, 10, 23, 22, 0), (2026, 10, 23, 9, 0)), ["Osaka"])


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TempDB()
        self.conn = self.tmp.__enter__()
        self.osaka = add_osaka(self.conn)
        # 3일 전 22시에 받은 예보가 있던 것처럼: 기온을 2도 높게 예보한 하루 통합 행 15개
        three_days_ago = TODAY - timedelta(days=3)
        old = openmeteo.to_slots(hourly_data(three_days_ago, 15, temp=12.0), self.osaka, three_days_ago,
                                 "2026-10-20T13:00:00+00:00")
        db.upsert_weather(self.conn, day_rows(old))

    def tearDown(self):
        self.tmp.__exit__()

    def test_저장하고_오늘_날짜_정확도_계산(self):
        run_at(self.conn, TOKYO_22)  # 오늘은 기온 10도
        n_slots = self.conn.execute("SELECT COUNT(*) FROM weather WHERE slot != 'day'").fetchone()[0]
        self.assertEqual(n_slots, 360)
        acc = [tuple(r) for r in self.conn.execute("SELECT target_date, lead_days, temp_max_diff, score FROM accuracy")]
        # 오늘(10/23)에 대한 3일 전 예보만 d0와 비교됨. 기온·체감 (2+2)/2/5 = 0.4씩 × 0.2 → 84점
        self.assertEqual(acc, [("2026-10-23", 3, 2.0, 84.0)])

    def test_recompute는_config_가중치를_다시_반영(self):
        run_at(self.conn, TOKYO_22)
        c = copy.deepcopy(cfg())
        c["accuracy"]["weights"] = {"temp": 1.0, "feel": 0.0, "prob": 0.0, "rain": 0.0, "weather": 0.0}
        self.assertEqual(accuracy.recompute(self.conn, c), 1)
        self.assertEqual(self.conn.execute("SELECT score FROM accuracy").fetchone()[0], 60.0)

    def test_fetch_실패는_error_log에_남음(self):
        clock, utc = fake_clock(TOKYO_22)
        failing = mock.patch.object(openmeteo, "fetch", side_effect=urllib.error.URLError("503"))
        with clock, utc, failing, self.assertRaises(SystemExit):
            collect.run(self.conn, cfg())
        rows = self.conn.execute("SELECT message, read_at FROM error_log").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("Osaka", rows[0]["message"])
        self.assertIsNone(rows[0]["read_at"])


class MigrateTest(unittest.TestCase):
    def test_예전_스키마에_체감온도_열을_더하고_날씨_열_이름을_바꿈(self):
        old = (db.SCHEMA.replace("  feel_max     REAL,", "").replace("  feel_min     REAL,", "")
               .replace("  feel_max_diff    REAL,", "").replace("  feel_min_diff    REAL,", "")
               .replace("weather_diff     REAL", "weather_severity REAL"))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.sqlite3"
            raw = sqlite3.connect(path)
            raw.executescript(old)
            raw.execute("INSERT INTO accuracy (target_date, city_id, lead_days, weather_severity, computed_at) "
                        "VALUES ('2026-10-23', 'c1', 1, 0.2, 't')")
            raw.commit()
            raw.close()
            conn = db.connect(path)
            cols = {t: {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")} for t in ("weather", "accuracy")}
            self.assertLessEqual({"feel_max", "feel_min"}, cols["weather"])
            self.assertLessEqual({"feel_max_diff", "feel_min_diff", "weather_diff"}, cols["accuracy"])
            self.assertNotIn("weather_severity", cols["accuracy"])
            self.assertEqual(conn.execute("SELECT weather_diff FROM accuracy").fetchone()[0], 0.2)  # 값은 그대로
            conn.close()
            db.connect(path).close()  # 두 번 열어도 그대로


if __name__ == "__main__":
    unittest.main()
