"""설치 TUI: 글자 폭·줄바꿈, 문구, 화면 흐름 (가짜 화면에 키를 넣어 돌린다, 네트워크·crontab 안 씀)."""

import curses
import subprocess
import unittest
from unittest import mock

from accu_weather import db, setup_tui
from accu_weather.setup_text import LANGUAGES, TEXT
from accu_weather.sources import openmeteo
from tests.fakes import TempDB, add_osaka

OSAKA = {"name": "Osaka", "admin1": "Osaka", "country": "Japan",
         "latitude": 34.69379, "longitude": 135.50107, "timezone": "Asia/Tokyo"}
OSAKA_US = {"name": "Osaka", "admin1": "Virginia", "country": "United States",
            "latitude": 36.94704, "longitude": -82.81072, "timezone": "America/New_York"}
DOWN, UP, DEL = curses.KEY_DOWN, curses.KEY_UP, curses.KEY_DC


class FakeScreen:
    """curses 화면 대신. get_wch는 keys를 차례로 돌려주고, 다 쓰면 실패시킨다 (무한 루프 방지)."""

    def __init__(self, keys, size=(24, 80)):
        self.keys = list(keys)
        self.size = size
        self.text = []  # 지금 화면
        self.history = []  # 지금까지 그린 모든 글자

    def getmaxyx(self):
        return self.size

    def get_wch(self):
        if not self.keys:
            raise AssertionError("키 입력이 더 필요함 (화면 흐름이 예상과 다름)")
        return self.keys.pop(0)

    def addstr(self, y, x, s, attr=0):
        self.text.append(s)
        self.history.append(s)

    def erase(self):
        self.text = []

    def hline(self, *a):
        pass

    def move(self, *a):
        pass

    def refresh(self):
        pass


def typed(s):
    return list(s)


class TextTest(unittest.TestCase):
    def test_모든_언어에_같은_문구_키(self):
        keys = set(TEXT["ko"])
        for code, _ in LANGUAGES:
            self.assertEqual(set(TEXT[code]), keys, code)

    def test_자리표시자_채우기(self):
        for code, _ in LANGUAGES:
            TEXT[code]["cron_body"].format(line="x")
            TEXT[code]["too_small"].format(w=1, h=1)
            TEXT[code]["done_cities"].format(n=1)


class WidthWrapTest(unittest.TestCase):
    def test_한글_일본어는_2칸(self):
        self.assertEqual(setup_tui.width("abc"), 3)
        self.assertEqual(setup_tui.width("도시"), 4)
        self.assertEqual(setup_tui.width("都市"), 4)

    def test_clip과_tail은_폭_기준(self):
        self.assertEqual(setup_tui.clip("도시검색", 5), "도시")
        self.assertEqual(setup_tui.tail("abc도시", 5), "c도시")

    def test_wrap은_어떤_줄도_폭을_넘지_않음(self):
        for code, _ in LANGUAGES:
            for n in (20, 37, 56):
                for line in setup_tui.wrap(TEXT[code]["intro_body"], n):
                    self.assertLessEqual(setup_tui.width(line), n, (code, n, line))

    def test_띄어쓰기_없는_긴_문장은_남은_칸부터_채움(self):
        self.assertEqual(setup_tui.wrap("ab あいうえお", 6), ["ab あ", "いうえ", "お"])
        self.assertEqual(setup_tui.wrap("abcdef あいうえお", 6), ["abcdef", "あいう", "えお"])  # 꽉 찬 줄 뒤

    def test_기본_언어는_LANG에서(self):
        for lang, expected in (("ko_KR.UTF-8", "ko"), ("ja_JP.UTF-8", "ja"), ("de_DE.UTF-8", "en"), ("", "en")):
            with mock.patch.dict("os.environ", {"LANG": lang, "LC_ALL": ""}):
                self.assertEqual(setup_tui.default_lang(), expected)


class SetupCase(unittest.TestCase):
    """임시 DB + 가짜 검색·crontab. 테스트는 아래 클래스들에."""

    def setUp(self):
        self.tmp = TempDB()
        self.conn = self.tmp.__enter__()
        patches = [
            mock.patch.object(curses, "ACS_HLINE", ord("-"), create=True),  # initscr 전에는 없음
            mock.patch.object(openmeteo, "geocode", return_value=[OSAKA, OSAKA_US]),
            mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")),
            mock.patch.dict("os.environ", {"LANG": "ko_KR.UTF-8", "LC_ALL": ""}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.__exit__()

    def run_setup(self, keys, size=(24, 80)):
        scr = FakeScreen(keys, size)
        result = setup_tui.Setup(scr, self.conn).run()
        self.assertEqual(scr.keys, [], "남은 키가 있음 (화면 흐름이 예상과 다름)")
        return result, scr

    def cities(self):
        return [(c["name"], c["country"]) for c in db.list_cities(self.conn)]

    def screen_title(self, scr):
        """지금 화면 제목 (frame이 그리는 세 번째 글자: 제목, 단계, 화면 제목)."""
        return scr.text[2]


class FlowTest(SetupCase):
    def test_처음부터_끝까지(self):
        keys = ["\n", "\n", "\n",  # 언어, 소개, 자동 실행 안내
                *typed("Osaka"), "\n",  # 검색 → 결과로 이동
                "\n", DOWN, "\n",  # 1번째, 2번째 후보 추가
                "\t", DOWN, DEL,  # 선택 목록에서 2번째 삭제
                "\t", "\n",  # 다음 버튼
                "\n",  # 설치
                "\n"]  # 완료 화면 닫기
        result, _ = self.run_setup(keys)
        self.assertEqual(self.cities(), [("Osaka", "Japan")])
        self.assertEqual(result["added"], 1)
        subprocess.run.assert_called_once()
        self.assertEqual(subprocess.run.call_args.args[0][-1], "install")

    def test_도시가_없으면_다음_버튼으로_못_감(self):
        # Tab: 검색 → 결과 → 선택 → (다음 없음) 검색. Enter는 빈 검색어라 아무 일 없음 → Esc로 나가서 q
        keys = ["\n", "\n", "\n", "\t", "\t", "\t", "\n", "\x1b", "q"]
        result, _ = self.run_setup(keys)
        self.assertIsNone(result)

    def test_같은_도시는_두_번_못_고름_이미_등록된_도시도(self):
        add_osaka(self.conn)
        keys = ["\n", "\n", "\n", *typed("Osaka"), "\n", "\n", "\t", "\t", "\n", "\n", "\n"]
        result, scr = self.run_setup(keys)
        self.assertEqual(result["added"], 0)
        self.assertEqual(len(self.cities()), 1)
        self.assertIn(TEXT["ko"]["already"], scr.history)

    def test_q로_나가면_아무것도_안_바뀜(self):
        keys = ["\n", "\n", "\n", *typed("Osaka"), "\n", "\n", "\t", "\t", "\n", "q"]
        result, _ = self.run_setup(keys)
        self.assertIsNone(result)
        self.assertEqual(self.cities(), [])
        subprocess.run.assert_not_called()

    def test_Esc로_이전_화면(self):
        keys = ["\n", "\n", "\x1b", "\x1b", "q"]  # 소개 → 안내 → 소개 → 언어 → 종료
        result, _ = self.run_setup(keys)
        self.assertIsNone(result)

    def test_Esc_검색어가_있으면_먼저_비우고_한_번_더_누르면_이전_화면(self):
        keys = ["\n", "\n", "\n", *typed("Osa"), "\x1b", "\x1b", "q"]
        _, scr = self.run_setup(keys)
        self.assertEqual(self.screen_title(scr), TEXT["ko"]["cron_title"])  # 도시 화면 바로 앞

    def test_Esc_목록에서는_검색창으로_돌아온_뒤_이전_화면(self):
        keys = ["\n", "\n", "\n", *typed("Osaka"), "\n", "\t", "\x1b", "\x1b", "q"]  # 결과 → 선택 목록에서 Esc
        _, scr = self.run_setup(keys)
        self.assertEqual(self.screen_title(scr), TEXT["ko"]["cron_title"])

    def test_검색_실패는_상태줄에_표시하고_계속(self):
        openmeteo.geocode.side_effect = OSError("network down")
        keys = ["\n", "\n", "\n", *typed("Osaka"), "\n", "\x1b", "\x1b", "q"]
        _, scr = self.run_setup(keys)
        self.assertTrue(any("network down" in t for t in scr.history))

    def test_창이_작으면_안내만_하고_키는_그대로_받음(self):
        result, scr = self.run_setup(["q"], size=(10, 40))
        self.assertIsNone(result)
        self.assertTrue(any("60x18" in t for t in scr.history))


class DockerModeTest(SetupCase):
    """컨테이너 안(ACCU_WEATHER_DOCKER=1): crontab 대신 수집 컨테이너 안내, run.sh는 부르지 않음."""

    def test_crontab_대신_컨테이너_안내(self):
        keys = ["\n", "\n", "\n", *typed("Osaka"), "\n", "\n", "\t", "\t", "\n", "\n", "\n"]
        with mock.patch.object(setup_tui, "IN_DOCKER", True), mock.patch.object(setup_tui, "WEB_PORT", "8080"):
            result, scr = self.run_setup(keys)
        self.assertEqual(self.cities(), [("Osaka", "Japan")])
        subprocess.run.assert_not_called()
        self.assertIn("docker compose up -d", result["cron"])
        self.assertTrue(any("http://<이 PC 주소>:8080" in t for t in scr.history))  # 완료 화면에 웹 주소
        self.assertIn(TEXT["ko"]["finish_docker"], scr.history)
        self.assertNotIn(setup_tui.CRON_LINE, scr.history)


class UnregisterTest(SetupCase):
    """이미 등록된 도시를 선택 목록에서 Del → 1 수집 중단 / 2 완전 삭제. 설치할 때 적용."""

    # 언어·소개·안내 → Tab 두 번으로 선택 목록(첫 줄 = 등록된 오사카)
    TO_SELECTED = ["\n", "\n", "\n", "\t", "\t"]
    INSTALL = ["\t", "\n", "\n", "\n"]  # 다음 버튼 → 설치 → 완료 닫기

    def setUp(self):
        super().setUp()
        self.osaka = add_osaka(self.conn)
        self.conn.execute(
            "INSERT INTO weather (target_date, slot, city_id, lead_days, source, fetched_at) "
            "VALUES ('2026-10-23', 'day', ?, 0, 'open-meteo', 't')", (self.osaka,))
        self.conn.commit()

    def osaka_row(self):
        return self.conn.execute("SELECT active FROM city WHERE city_id = ?", (self.osaka,)).fetchone()

    def weather_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM weather WHERE city_id = ?", (self.osaka,)).fetchone()[0]

    def test_1_수집_중단은_데이터_유지(self):
        result, _ = self.run_setup([*self.TO_SELECTED, DEL, "1", *self.INSTALL])
        self.assertEqual(self.osaka_row()["active"], 0)
        self.assertEqual(self.weather_count(), 1)
        self.assertEqual((result["stopped"], result["purged"]), (1, 0))

    def test_2_완전_삭제는_데이터까지(self):
        result, _ = self.run_setup([*self.TO_SELECTED, DEL, "2", *self.INSTALL])
        self.assertIsNone(self.osaka_row())
        self.assertEqual(self.weather_count(), 0)
        self.assertEqual((result["stopped"], result["purged"]), (0, 1))

    def test_다시_Del하면_표시_해제(self):
        result, _ = self.run_setup([*self.TO_SELECTED, DEL, "2", DEL, *self.INSTALL])
        self.assertEqual(self.osaka_row()["active"], 1)
        self.assertEqual((result["stopped"], result["purged"]), (0, 0))

    def test_1_2가_아닌_키는_취소(self):
        result, _ = self.run_setup([*self.TO_SELECTED, DEL, "\x1b", *self.INSTALL])
        self.assertEqual(self.osaka_row()["active"], 1)

    def test_설치_전에_나가면_적용_안_됨(self):
        result, _ = self.run_setup([*self.TO_SELECTED, DEL, "2", "\t", "\n", "q"])
        self.assertIsNone(result)
        self.assertEqual(self.weather_count(), 1)

    def test_설치_화면에_등록_취소_목록_표시(self):
        _, scr = self.run_setup([*self.TO_SELECTED, DEL, "2", "\t", "\n", "q"])
        self.assertIn(TEXT["ko"]["finish_purge"], scr.text)
        self.assertIn("· Osaka, Japan", scr.text)


if __name__ == "__main__":
    unittest.main()
