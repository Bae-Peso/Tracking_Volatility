"""웹 조회: 데이터 계층(queries, 표준 라이브러리만)과 Flask 엔드포인트(Flask가 있을 때만)."""

import math
import tempfile
import unittest
from pathlib import Path

from accu_weather import codes, db
from tests.fakes import cfg
from web import queries

try:
    import flask  # noqa: F401
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

ACC = cfg()["accuracy"]


def row(city_id, target, lead, slot="day", code=0, temp_max=20.0, temp_min=10.0, precip=0.0, prob=0,
        wind=5.0, vis=20000.0):
    return {
        "target_date": target, "slot": slot, "city_id": city_id, "lead_days": lead,
        "weather": codes.category(code), "weather_code": code, "temp_max": temp_max, "temp_min": temp_min,
        "feel_max": temp_max + 1, "feel_min": temp_min - 2,
        "wind_kmh": wind, "visibility_m": vis, "precip_mm": precip, "precip_prob": prob,
        "source": "open-meteo", "fetched_at": "t",
    }


class WebDB(unittest.TestCase):
    """임시 DB: 11/1은 d0 + 1·3일전, 11/2는 d0 없이 2일전만, 11/3은 d0 + 14일전."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "t.sqlite3"
        conn = db.connect(self.path)
        self.city = db.add_city(conn, "Osaka", "Japan", 34.69, 135.50, "Asia/Tokyo")
        db.upsert_weather(conn, [
            row(self.city, "2026-11-01", 0, code=0, temp_max=20.0, precip=0.0, prob=0),
            row(self.city, "2026-11-01", 1, code=0, temp_max=21.0, precip=0.0, prob=10),
            row(self.city, "2026-11-01", 3, code=61, temp_max=17.0, precip=10.0, prob=60),
            row(self.city, "2026-11-02", 2),
            row(self.city, "2026-11-03", 0, temp_max=15.0),
            row(self.city, "2026-11-03", 14, temp_max=30.0),
        ])
        conn.close()
        self.conn = queries.connect_ro(self.path)

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()


class CalendarTest(WebDB):
    def test_d0가_있는_날짜만_n일전_14칸(self):
        days = queries.calendar(self.conn, self.city, "2026-11-01", "2026-11-30", "temp_max", ACC)
        self.assertEqual(sorted(days), ["2026-11-01", "2026-11-03"])  # 11/2는 d0 없음
        nov1 = days["2026-11-01"]
        self.assertEqual(len(nov1["values"]), 14)
        self.assertEqual(nov1["values"][:4], [1.0, None, -3.0, None])  # 1·3일전만, 차이 = n일전 − d0
        self.assertEqual(nov1["bad"][:3], [0.2, None, 0.6])  # |차이| / 5℃
        # 주간 '당일' 열·월간 칸에 쓰는 당일 예보 요약
        self.assertEqual(nov1["d0"], {"weather_code": 0, "temp_max": 20.0, "temp_min": 10.0, "value": 20.0})

    def test_점수와_날씨는_당일_값이_없음(self):
        for metric in ("score", "weather"):
            days = queries.calendar(self.conn, self.city, "2026-11-01", "2026-11-01", metric, ACC)
            self.assertIsNone(days["2026-11-01"]["d0"]["value"], metric)

    def test_기준값_이상은_1로_자름(self):
        days = queries.calendar(self.conn, self.city, "2026-11-03", "2026-11-03", "temp_max", ACC)
        self.assertEqual(days["2026-11-03"]["values"][13], 15.0)
        self.assertEqual(days["2026-11-03"]["bad"][13], 1.0)

    def test_항목별_색_정도(self):
        def bad(metric):
            return queries.calendar(self.conn, self.city, "2026-11-01", "2026-11-01", metric, ACC)["2026-11-01"]["bad"][2]

        self.assertAlmostEqual(bad("precip_prob"), 0.6)
        self.assertAlmostEqual(bad("precip"), round(math.sqrt(10) / math.sqrt(ACC["rain_worst_mm"]), 3))
        self.assertAlmostEqual(bad("weather"), 0.35)  # 맑음(0) ↔ 약한 비(가중치 0.35)
        self.assertAlmostEqual(bad("feel_max"), 3 / ACC["temp_worst_c"])  # 체감도 기온처럼 차이 / 기준값
        score = queries.calendar(self.conn, self.city, "2026-11-01", "2026-11-01", "score", ACC)["2026-11-01"]
        self.assertEqual(score["bad"][2], round(min(1, (100 - score["values"][2]) / 50), 3))

    def test_날씨와_강수확률은_1시간_슬롯도_비교(self):
        # 11/5: 하루 대표는 둘 다 강한 비·80%. d0는 0~17시 비·0~11시 80%, 1일전은 0~2시 비·6~17시 80%
        conn = db.connect(self.path)
        rows = [row(self.city, "2026-11-05", lead, code=65, prob=80) for lead in (0, 1)]
        for lead, rain, wet in ((0, range(18), range(12)), (1, range(3), range(6, 18))):
            rows += [row(self.city, "2026-11-05", lead, slot=f"{h:02d}", code=65 if h in rain else 3,
                         prob=80 if h in wet else 0) for h in range(24)]
        db.upsert_weather(conn, rows)
        conn.close()

        def first(metric):
            d = queries.calendar(self.conn, self.city, "2026-11-05", "2026-11-05", metric, ACC)["2026-11-05"]
            return d["values"][0], d["bad"][0]

        self.assertEqual(first("weather"), (0.125, 0.125))  # 0.5 × 0 + 0.5 × (5묶음 × 0.4 / 8)
        self.assertEqual(first("precip_prob"), (0, 0.2))  # 값은 하루 최대 차이, 색은 0.5 × 0 + 0.5 × 40%p
        lead1 = next(l for l in queries.day(self.conn, self.city, "2026-11-05", ACC)["leads"] if l["lead"] == 1)
        self.assertEqual(lead1["diffs"]["weather"], 0.125)
        self.assertEqual(lead1["score"], 100 * (1 - 0.2 * (0.125 + 0.2)))

    def test_없는_항목은_오류(self):
        with self.assertRaises(ValueError):
            queries.calendar(self.conn, self.city, "2026-11-01", "2026-11-01", "nope", ACC)


class DayTest(WebDB):
    def test_14일전부터_당일까지_15줄(self):
        d = queries.day(self.conn, self.city, "2026-11-01", ACC)
        self.assertTrue(d["has_d0"])
        self.assertEqual(d["d0_weather_code"], 0)  # 이름은 화면이 언어에 맞게 (weather_names)
        self.assertEqual([l["lead"] for l in d["leads"]], list(range(14, -1, -1)))
        by_lead = {l["lead"]: l for l in d["leads"]}
        self.assertFalse(by_lead[2]["available"])
        self.assertEqual(by_lead[3]["diffs"]["temp_max"], -3.0)
        self.assertEqual(by_lead[3]["diffs"]["feel_max"], -3.0)
        self.assertEqual(by_lead[3]["values"]["feel_max"], 18.0)
        self.assertEqual(by_lead[3]["diffs"]["precip"], 10.0)
        self.assertEqual(by_lead[3]["weather_match"], 0)
        self.assertEqual(by_lead[3]["weather_code"], 61)
        self.assertEqual(by_lead[0]["diffs"]["temp_max"], 0)  # 당일 = 0
        self.assertIsNone(by_lead[0]["score"])
        self.assertIsNotNone(by_lead[1]["score"])

    def test_d0가_없으면_차이는_None(self):
        d = queries.day(self.conn, self.city, "2026-11-02", ACC)
        self.assertFalse(d["has_d0"])
        lead2 = next(l for l in d["leads"] if l["lead"] == 2)
        self.assertIsNone(lead2["diffs"])
        self.assertEqual(lead2["values"]["temp_max"], 20.0)


class SeriesTest(WebDB):
    def setUp(self):
        super().setUp()
        conn = db.connect(self.path)
        slots = []
        for day in range(1, 31):  # 11월 한 달, 당일 예보 1시간 슬롯 24개씩
            for hour in range(24):
                slots.append(row(self.city, f"2026-11-{day:02d}", 0, slot=f"{hour:02d}",
                                 temp_max=float(hour), temp_min=float(hour), precip=0.5))
        db.upsert_weather(conn, slots)
        conn.close()

    def test_1시간_단위(self):
        s = queries.series(self.conn, self.city, "2026-11-01", "2026-11-14", "temp_max", "slot")
        self.assertFalse(s["daily"])
        self.assertEqual(len(s["leads"]["0"]), 14 * 24)
        self.assertEqual(s["leads"]["0"][:2], [["2026-11-01T00:00", 0.0], ["2026-11-01T01:00", 1.0]])

    def test_여러_시간으로_묶기는_하루_통합과_같은_규칙(self):
        s = queries.series(self.conn, self.city, "2026-11-01", "2026-11-01", "temp_max", "slot", hours=3)
        self.assertEqual(s["leads"]["0"][:2], [["2026-11-01T00:00", 2.0], ["2026-11-01T03:00", 5.0]])
        lo = queries.series(self.conn, self.city, "2026-11-01", "2026-11-01", "temp_min", "slot", hours=12)
        self.assertEqual(lo["leads"]["0"], [["2026-11-01T00:00", 0.0], ["2026-11-01T12:00", 12.0]])
        rain = queries.series(self.conn, self.city, "2026-11-01", "2026-11-01", "precip", "slot", hours=6)
        self.assertEqual([v for _, v in rain["leads"]["0"]], [3.0] * 4)
        with self.assertRaises(ValueError):
            queries.series(self.conn, self.city, "2026-11-01", "2026-11-01", "temp_max", "slot", hours=5)

    def test_하루_단위는_일간_보기와_같은_하루_통합_값(self):
        # 1시간 슬롯을 평균내지 않고, 저장된 하루 통합 행(최고기온 = 그날 최대)을 그대로 쓴다
        s = queries.series(self.conn, self.city, "2026-11-01", "2026-11-21", "temp_max", "day")
        self.assertTrue(s["daily"])
        self.assertEqual(s["leads"]["0"], [["2026-11-01", 20.0], ["2026-11-03", 15.0]])
        self.assertEqual(s["leads"]["3"], [["2026-11-01", 17.0]])
        p = queries.series(self.conn, self.city, "2026-11-01", "2026-11-01", "precip", "day")
        self.assertEqual(p["leads"]["3"], [["2026-11-01", 10.0]])

    def test_단위를_직접_지정(self):
        self.assertTrue(queries.series(self.conn, self.city, "2026-11-01", "2026-11-02", "temp_max", "day")["daily"])
        self.assertFalse(queries.series(self.conn, self.city, "2026-11-01", "2026-11-30", "temp_max", "slot")["daily"])
        with self.assertRaises(ValueError):
            queries.series(self.conn, self.city, "2026-11-01", "2026-11-02", "temp_max", "week")

    def test_날씨는_값이_아니라_d0와의_변동성(self):
        # 11/1: d0 맑음, 1일전 맑음 → 0, 3일전 약한 비(가중치 0.35) → 0.35. 11/2는 d0가 없어 점 없음
        s = queries.series(self.conn, self.city, "2026-11-01", "2026-11-03", "weather", "day")
        self.assertNotIn("0", s["leads"])  # 당일 자신의 선은 없음
        self.assertEqual(s["leads"]["1"], [["2026-11-01", 0.0]])
        self.assertEqual(s["leads"]["3"], [["2026-11-01", 0.35]])
        self.assertEqual(s["leads"]["2"], [])
        self.assertEqual(s["leads"]["14"], [["2026-11-03", 0.0]])

    def test_날씨_값은_일간_보기에도_없음(self):
        d = queries.day(self.conn, self.city, "2026-11-02", ACC)  # d0 없음
        lead2 = next(l for l in d["leads"] if l["lead"] == 2)
        self.assertIsNone(lead2["values"]["weather"])
        self.assertIsNone(lead2["diffs"])

    def test_하루_통합_행은_그래프에_안_들어감(self):
        s = queries.series(self.conn, self.city, "2026-11-01", "2026-11-03", "temp_max", "slot")
        self.assertNotIn("1", s["leads"])  # 1·3·14일전은 하루 통합 행만 있음


class RangeTest(unittest.TestCase):
    def test_순서_바꿈과_길이_제한(self):
        self.assertEqual(queries.clamp_range("2026-11-10", "2026-11-01"), ("2026-11-01", "2026-11-10"))
        with self.assertRaises(ValueError):
            queries.clamp_range("2025-01-01", "2026-12-31")
        with self.assertRaises(ValueError):
            queries.clamp_range("2026-13-01", "2026-12-31")
        # 그래프는 최대 2년 + 앞으로 14일
        queries.clamp_range("2024-10-23", "2026-11-06", queries.SERIES_MAX_DAYS)


@unittest.skipUnless(HAS_FLASK, "Flask 없음 (pip install -r web/requirements.txt)")
class ApiTest(WebDB):
    def setUp(self):
        super().setUp()
        from web.app import create_app

        self.client = create_app(self.path).test_client()

    def test_화면과_메타(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        meta = self.client.get("/api/meta").get_json()
        self.assertEqual(meta["leads"], list(range(1, 15)))
        # 날씨 이름은 weather_code.json의 언어별 이름을 그대로 넘긴다 (화면 i18n)
        self.assertEqual(meta["weather_names"]["61"], {"en": "Slight rain", "ko": "약한 비", "ja": "弱い雨"})
        self.assertEqual(meta["worst"]["temp_max"], ACC["temp_worst_c"])

    def test_도시와_달력(self):
        cities = self.client.get("/api/cities").get_json()
        self.assertEqual([c["name"] for c in cities], ["Osaka"])
        self.assertIn("today", cities[0])
        r = self.client.get(f"/api/calendar?city={self.city}&start=2026-11-01&end=2026-11-30&metric=temp_max")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(r.get_json()["days"]), ["2026-11-01", "2026-11-03"])

    def test_일간과_그래프(self):
        d = self.client.get(f"/api/day?city={self.city}&date=2026-11-01").get_json()
        self.assertEqual(len(d["leads"]), 15)
        s = self.client.get(f"/api/series?city={self.city}&start=2026-11-01&end=2026-11-02&metric=wind")
        self.assertEqual(s.status_code, 200)
        s6 = self.client.get(f"/api/series?city={self.city}&start=2026-11-01&end=2026-11-02&metric=wind&hours=6")
        self.assertEqual(s6.status_code, 200)
        two_years = self.client.get(f"/api/series?city={self.city}&start=2024-10-23&end=2026-11-06&metric=temp_max&step=day")
        self.assertEqual(two_years.status_code, 200)
        self.assertTrue(two_years.get_json()["daily"])

    def test_오류는_문구_대신_코드(self):
        r = self.client.get("/api/calendar?city=nope&start=2026-11-01&end=2026-11-02").get_json()
        self.assertEqual(r["error"], "unknown_city")
        r = self.client.get(f"/api/series?city={self.city}&start=2020-01-01&end=2026-11-02").get_json()
        self.assertEqual((r["error"], r["detail"]), ("range_too_long", queries.SERIES_MAX_DAYS))

    def test_잘못된_입력은_400(self):
        for url in ["/api/calendar?city=nope&start=2026-11-01&end=2026-11-02",
                    f"/api/calendar?city={self.city}&start=2026-11-01",
                    f"/api/calendar?city={self.city}&start=2026-11-01&end=2026-11-02&metric=zzz",
                    f"/api/day?city={self.city}&date=11/01",
                    f"/api/series?city={self.city}&start=2020-01-01&end=2026-11-02",
                    f"/api/series?city={self.city}&start=2026-11-01&end=2026-11-02&step=week",
                    f"/api/series?city={self.city}&start=2026-11-01&end=2026-11-02&hours=5"]:
            self.assertEqual(self.client.get(url).status_code, 400, url)

    def test_수집_실패_알림은_미확인만_최근부터(self):
        conn = db.connect(self.path)
        db.log_error(conn, "fetch failed (Osaka): 503")
        db.log_error(conn, "fetch failed (Osaka): timeout")
        conn.execute("UPDATE error_log SET read_at = 't' WHERE error_id = 1")
        conn.commit()
        conn.close()
        errors = self.client.get("/api/errors").get_json()
        self.assertEqual([e["message"] for e in errors], ["fetch failed (Osaka): timeout"])

    def test_DB가_없으면_503(self):
        from web.app import create_app

        client = create_app(Path(self.dir.name) / "none.sqlite3").test_client()
        self.assertEqual(client.get("/api/cities").status_code, 503)

    def test_읽기_전용(self):
        import sqlite3

        with self.assertRaises(sqlite3.OperationalError):
            self.conn.execute("DELETE FROM city")


if __name__ == "__main__":
    unittest.main()


class I18nFilesTest(unittest.TestCase):
    """web/static/i18n: 언어를 추가할 때 빠진 키나 틀린 {자리표시자}를 잡아낸다."""

    DIR = Path(__file__).resolve().parent.parent / "web" / "static" / "i18n"

    def load(self, name):
        import json

        return json.loads((self.DIR / name).read_text(encoding="utf-8"))

    def test_목록의_언어마다_파일이_있고_키와_자리표시자가_영어와_같음(self):
        import re

        base = self.load("en.json")
        # 화면 코드가 넘겨주는 변수: 기본은 영어 문구의 것, 언어마다 골라 쓰는 키는 따로
        allowed = {"period_month": {"y", "m", "mon"}}

        def holes(v):
            return set(re.findall(r"\{(\w+)\}", v)) if isinstance(v, str) else None

        for lang in self.load("languages.json"):
            d = self.load(f"{lang['code']}.json")
            self.assertEqual(set(d), set(base), lang["code"])
            for k, v in d.items():
                if isinstance(base[k], list):
                    self.assertEqual(len(v), len(base[k]), f"{lang['code']}: {k}")
                else:
                    self.assertLessEqual(holes(v), allowed.get(k, holes(base[k])), f"{lang['code']}: {k}")

    def test_날씨_이름도_모든_언어에(self):
        from accu_weather import codes

        langs = [l["code"] for l in self.load("languages.json")]
        for code, entry in codes.WEATHER_CODES.items():
            for lang in langs:
                self.assertIn(lang, entry, f"weather_code.json {code}: {lang}")
