"""설치용 TUI (python3 -m accu_weather setup). 표준 라이브러리 curses만 쓴다.

화면 순서: 1 언어 → 2 소개 → 3 자동 실행 안내 → 4 도시 추가 → 5 설치 → 완료
마지막 설치 화면에서 Enter를 누르기 전에는 DB와 crontab을 건드리지 않는다 (도시 추가·등록 취소 모두).
"""

import curses
import locale
import os
import sqlite3
import subprocess
import sys
import unicodedata

from . import config, db
from .setup_text import LANGUAGES, TEXT
from .sources import openmeteo

MIN_W, MIN_H = 60, 18
STEPS = 5
CRON_LINE = f"*/30 * * * *  {config.ROOT / 'run.sh'}"  # run.sh install이 등록하는 줄과 같음
IN_DOCKER = os.environ.get("ACCU_WEATHER_DOCKER") == "1"  # Dockerfile이 설정. crontab 대신 serve 컨테이너가 수집
DOCKER_UP = "docker compose up -d"

ENTER = ("\n", "\r", curses.KEY_ENTER)
ESC = "\x1b"
BACKSPACE = ("\x7f", "\b", curses.KEY_BACKSPACE)


# ---- 글자 폭 (한글·일본어는 터미널에서 2칸) ----

def width(s):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def clip(s, n):
    """앞에서부터 폭 n칸까지."""
    out, w = "", 0
    for ch in s:
        if w + width(ch) > n:
            break
        out += ch
        w += width(ch)
    return out


def tail(s, n):
    """뒤에서부터 폭 n칸까지 (입력 칸이 넘칠 때 끝부분을 보여줌)."""
    while width(s) > n:
        s = s[1:]
    return s


def wrap(text, n):
    """폭 n칸으로 줄바꿈. 한 줄보다 긴 단어(띄어쓰기 없는 일본어 문장 등)는 남은 칸부터 글자 단위로 채운다."""
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            candidate = f"{line} {word}" if line else word
            if width(candidate) <= n:
                line = candidate
            elif width(word) <= n:
                lines.append(line)
                line = word
            else:
                if line and width(line) + 1 < n:
                    line += " "
                elif line:
                    lines.append(line)
                    line = ""
                for ch in word:
                    if width(line + ch) > n:
                        lines.append(line)
                        line = ""
                    line += ch
        lines.append(line)
    return lines


# ---- 도시 ----

def result_label(c):
    """검색 결과 → 'Osaka, Osaka, Japan' (도시, 지역, 국가)."""
    return ", ".join(x for x in (c["name"], c.get("admin1"), c.get("country")) if x)


def same_place(a, b):
    """좌표가 소수 둘째 자리까지 같으면 같은 도시 (DB의 UNIQUE와 같은 기준)."""
    return (round(a["latitude"], 2), round(a["longitude"], 2)) == (round(b["latitude"], 2), round(b["longitude"], 2))


def default_lang():
    env = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    return next((code for code, _ in LANGUAGES if env.startswith(code)), "en")


class Setup:
    def __init__(self, scr, conn):
        self.scr = scr
        self.conn = conn
        self.lang = default_lang()
        self.existing = db.list_cities(conn)  # 이미 등록된 도시
        self.picked = []  # 이번에 고른 도시 (geocoding 결과)
        self.removals = {}  # 등록 취소할 도시 {city_id: "stop" | "purge"} (설치할 때 적용)
        self.confirm = None  # 등록 취소 방법을 묻는 중인 도시
        # 도시 화면 상태
        self.query = ""
        self.results = []
        self.res_i = 0
        self.sel_i = 0
        self.focus = "search"  # search / results / selected / next
        self.status = ""

    def t(self, key, **kw):
        return TEXT[self.lang][key].format(**kw)

    # ---- 그리기 ----

    def put(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and 0 <= x < w - 1:
            try:
                self.scr.addstr(y, x, clip(text, w - 1 - x), attr)
            except curses.error:
                pass

    def paragraph(self, y, x, w, bottom, text):
        """줄바꿈해서 그리고 다음 줄 y를 돌려준다."""
        for line in wrap(text, w):
            if y > bottom:
                break
            self.put(y, x, line)
            y += 1
        return y

    def cursor(self, visible):
        try:
            curses.curs_set(1 if visible else 0)
        except curses.error:
            pass

    def frame(self, step, title, keys):
        """공통 틀(제목, 단계, 구분선, 키 안내). 본문 영역 (top, bottom, width), 창이 너무 작으면 None."""
        self.scr.erase()
        self.cursor(False)
        h, w = self.scr.getmaxyx()
        if h < MIN_H or w < MIN_W:
            for y, line in enumerate(wrap(self.t("too_small", w=MIN_W, h=MIN_H), w - 1)):
                self.put(y, 0, line)
            return None
        self.put(0, 2, self.t("title"), curses.A_BOLD)
        if step:
            self.put(0, w - 2 - len(f"{step}/{STEPS}"), f"{step}/{STEPS}")
        self.scr.hline(1, 0, curses.ACS_HLINE, w)
        self.put(2, 2, title, curses.A_BOLD)
        self.scr.hline(h - 2, 0, curses.ACS_HLINE, w)
        self.put(h - 1, 2, keys, curses.A_DIM)
        return 4, h - 3, w

    def draw_list(self, top, bottom, x, w, items, cur, focused):
        rows = bottom - top + 1
        start = max(0, cur - rows + 1)
        for n, item in enumerate(items[start:start + rows]):
            i = start + n
            attr = (curses.A_REVERSE if focused else curses.A_BOLD) if i == cur else 0
            self.put(top + n, x, clip(f"{'>' if i == cur else ' '} {item}", w).ljust(w), attr)

    @staticmethod
    def nav(k):
        if k in ENTER:
            return "next"
        if k in (ESC, curses.KEY_LEFT):
            return "back"
        if k in ("q", "Q"):
            return "quit"
        return None

    # ---- 1. 언어 ----

    def screen_lang(self):
        codes = [code for code, _ in LANGUAGES]
        i = codes.index(self.lang)
        while True:
            area = self.frame(1, self.t("lang_title"), self.t("keys_nav"))
            if area:
                top, bottom, w = area
                y = self.paragraph(top, 2, w - 4, bottom, self.t("lang_body")) + 1
                self.draw_list(y, y + len(LANGUAGES) - 1, 4, 20, [name for _, name in LANGUAGES], i, True)
            k = self.scr.get_wch()
            if k in (curses.KEY_UP, curses.KEY_DOWN):
                i = (i + (1 if k == curses.KEY_DOWN else -1)) % len(codes)
                self.lang = codes[i]  # 고르는 동안 바로 그 언어로 보여줌
            elif self.nav(k):
                return self.nav(k)

    # ---- 2, 3. 안내문 ----

    def screen_text(self, step, title_key, body_key, **kw):
        while True:
            area = self.frame(step, self.t(title_key), self.t("keys_nav"))
            if area:
                top, bottom, w = area
                self.paragraph(top, 2, w - 4, bottom, self.t(body_key, **kw))
            k = self.scr.get_wch()
            if self.nav(k):
                return self.nav(k)

    # ---- 4. 도시 추가 ----

    def existing_label(self, c):
        how = self.removals.get(c["city_id"])
        mark = {"stop": "mark_stop", "purge": "mark_purge"}.get(how) or ("registered" if c["active"] else "inactive")
        return f"{c['name']}, {c['country'] or '-'} {self.t(mark)}"

    def selected_rows(self):
        """선택 목록: 이미 등록된 도시 다음에 이번에 고른 도시. (라벨, 등록된 도시 행 또는 None)"""
        rows = [(self.existing_label(c), c) for c in self.existing]
        return rows + [(result_label(c), None) for c in self.picked]

    def can_next(self):
        return bool(self.existing or self.picked)

    def draw_cities(self):
        area = self.frame(4, self.t("cities_title"), self.t("cities_keys"))
        if not area:
            return
        top, bottom, w = area
        label = self.t("search_label")
        self.put(top, 2, label)
        x = 2 + width(label)
        field_w = max(10, w - x - 3)
        shown = tail(self.query, field_w - 1)
        field_attr = curses.A_REVERSE if self.focus == "search" else curses.A_UNDERLINE
        self.put(top, x, shown + " " * (field_w - width(shown)), field_attr)
        # 상태줄: 검색창 아래 2줄 (등록 취소 안내, 오류 메시지가 길면 줄바꿈)
        message = self.t("unregister_prompt", name=self.confirm["name"]) if self.confirm else self.status
        for n, line in enumerate(wrap(message, w - 4)[:2]):
            self.put(top + 1 + n, 2, line, curses.A_BOLD if self.confirm else curses.A_DIM)

        col_w = (w - 6) // 2
        list_top, list_bottom = top + 4, bottom - 2
        self.put(top + 3, 2, self.t("results"), curses.A_BOLD)
        self.put(top + 3, 4 + col_w, self.t("selected"), curses.A_BOLD)
        self.draw_list(list_top, list_bottom, 2, col_w, [result_label(c) for c in self.results],
                       self.res_i, self.focus == "results")
        self.draw_list(list_top, list_bottom, 4 + col_w, col_w, [r[0] for r in self.selected_rows()],
                       self.sel_i, self.focus == "selected")
        if self.can_next():
            attr = curses.A_BOLD | (curses.A_REVERSE if self.focus == "next" else 0)
            self.put(bottom, w - 4 - width(self.t("next_button")), self.t("next_button"), attr)
        if self.focus == "search":
            self.cursor(True)
            self.scr.move(top, x + width(shown))

    def search(self):
        query = self.query.strip()
        if not query:
            return
        self.status = self.t("searching")
        self.draw_cities()
        self.scr.refresh()
        try:
            self.results = openmeteo.geocode(query, count=10)
        except (OSError, ValueError) as e:  # 네트워크 오류, 응답 오류
            self.results, self.status = [], self.t("search_failed", e=e)
            return
        self.res_i = 0
        if self.results:
            self.status, self.focus = "", "results"
        else:
            self.status = self.t("no_results")

    def pick(self):
        c = dict(self.results[self.res_i])
        if any(same_place(c, other) for other in [*self.existing, *self.picked]):
            self.status = self.t("already")
            return
        if not c.get("timezone"):
            try:
                c["timezone"] = openmeteo.lookup_timezone(c["latitude"], c["longitude"])
            except (OSError, ValueError) as e:
                self.status = self.t("search_failed", e=e)
                return
        self.picked.append(c)
        self.status = self.t("added", name=result_label(c))

    def remove(self):
        """선택 목록에서 Del: 고른 도시는 빼고, 등록된 도시는 취소 방법을 묻는다 (표시된 도시는 표시 해제)."""
        rows = self.selected_rows()
        if not rows:
            return
        label, city = rows[self.sel_i]
        if city is None:
            del self.picked[self.sel_i - len(self.existing)]
            self.sel_i = max(0, min(self.sel_i, len(self.selected_rows()) - 1))
            self.status = self.t("removed", name=label)
        elif city["city_id"] in self.removals:
            del self.removals[city["city_id"]]
            self.status = self.t("unmarked", name=city["name"])
        else:
            self.confirm = city

    def answer_confirm(self, k):
        city, self.confirm = self.confirm, None
        if k == "1" and not city["active"]:
            self.status = self.t("already_stopped", name=city["name"])
        elif k in ("1", "2"):
            self.removals[city["city_id"]] = "stop" if k == "1" else "purge"
            self.status = self.t("marked", name=city["name"])
        else:
            self.status = ""

    def screen_cities(self):
        while True:
            self.draw_cities()
            k = self.scr.get_wch()
            order = ["search", "results", "selected"] + (["next"] if self.can_next() else [])
            if self.confirm:
                self.answer_confirm(k)  # 1 / 2 / 그 밖의 키(Esc 등)는 취소
            elif k == ESC:
                # 검색어가 있거나 목록에 있으면: 검색창 비우고 검색창으로. 빈 검색창에서 한 번 더: 이전 화면
                if self.query or self.focus != "search":
                    self.query, self.focus, self.status = "", "search", ""
                else:
                    return "back"
            elif k in ("\t", curses.KEY_BTAB):
                i = order.index(self.focus) if self.focus in order else 0
                self.focus = order[(i + (1 if k == "\t" else -1)) % len(order)]
            elif self.focus == "search":
                if k in ENTER:
                    self.search()
                elif k in BACKSPACE:
                    self.query = self.query[:-1]
                elif k == curses.KEY_DOWN and self.results:
                    self.focus = "results"
                elif isinstance(k, str) and k.isprintable():
                    self.query += k
            elif self.focus == "results":
                if k == curses.KEY_UP and self.res_i == 0:
                    self.focus = "search"
                elif k in (curses.KEY_UP, curses.KEY_DOWN) and self.results:
                    self.res_i = max(0, min(len(self.results) - 1, self.res_i + (1 if k == curses.KEY_DOWN else -1)))
                elif k in ENTER and self.results:
                    self.pick()
                elif isinstance(k, str) and k.isprintable():  # 바로 타이핑하면 새 검색어로
                    self.focus, self.query = "search", k
            elif self.focus == "selected":
                rows = self.selected_rows()
                if k in (curses.KEY_UP, curses.KEY_DOWN) and rows:
                    self.sel_i = max(0, min(len(rows) - 1, self.sel_i + (1 if k == curses.KEY_DOWN else -1)))
                elif k in (curses.KEY_DC, *BACKSPACE):
                    self.remove()
            elif self.focus == "next" and k in ENTER:
                return "next"
            if self.focus == "next" and not self.can_next():
                self.focus = "selected"

    # ---- 5. 설치 ----

    def finish_sections(self):
        """(제목, 줄들, 강조) — 비어 있는 등록 취소 항목은 뺀다."""
        names = {c["city_id"]: f"{c['name']}, {c['country'] or '-'}" for c in self.existing}
        stop = [names[i] for i, how in self.removals.items() if how == "stop"]
        purge = [names[i] for i, how in self.removals.items() if how == "purge"]
        sections = [(self.t("finish_new"), [result_label(c) for c in self.picked] or [self.t("finish_none")], 0)]
        if stop:
            sections.append((self.t("finish_stop"), stop, 0))
        if purge:
            sections.append((self.t("finish_purge"), purge, curses.A_BOLD))
        return sections

    def screen_finish(self):
        while True:
            area = self.frame(5, self.t("finish_title"), self.t("finish_keys"))
            if area:
                top, bottom, w = area
                y = self.paragraph(top, 2, w - 4, bottom, self.t("finish_body")) + 1
                sections = self.finish_sections()
                room = max(1, (bottom - y - 3) // len(sections) - 2)  # 항목마다 보여줄 줄 수
                for title, lines, attr in sections:
                    self.put(y, 2, title, curses.A_BOLD)
                    if len(lines) > room:
                        lines = lines[:room - 1] + [f"… +{len(lines) - room + 1}"]
                    for n, line in enumerate(lines):
                        self.put(y + 1 + n, 4, f"· {line}", attr)
                    y += len(lines) + 2
                self.put(y, 2, self.t("finish_docker" if IN_DOCKER else "finish_cron"), curses.A_BOLD)
                self.put(y + 1, 4, DOCKER_UP if IN_DOCKER else CRON_LINE)
            k = self.scr.get_wch()
            if self.nav(k):
                return self.nav(k)

    def apply(self):
        result = {"added": 0, "stopped": 0, "purged": 0}
        for city_id, how in self.removals.items():
            if how == "purge":
                db.purge_city(self.conn, city_id)
                result["purged"] += 1
            else:
                db.set_active(self.conn, city_id, False)
                result["stopped"] += 1
        for c in self.picked:
            try:
                db.add_city(self.conn, c["name"], c.get("country"), c["latitude"], c["longitude"], c["timezone"])
                result["added"] += 1
            except sqlite3.IntegrityError:  # 그새 다른 곳에서 등록됨
                pass
        if IN_DOCKER:
            result["cron"] = self.t("done_docker", up=DOCKER_UP)
            return result
        r = subprocess.run(["bash", str(config.ROOT / "run.sh"), "install"], capture_output=True, text=True)
        result["cron"] = (self.t("done_cron") if r.returncode == 0
                          else self.t("done_cron_failed", e=(r.stderr or r.stdout).strip()))
        return result

    def screen_done(self, result):
        lines = [self.t("done_cities", n=result["added"])]
        if result["stopped"] or result["purged"]:
            lines.append(self.t("done_removed", stopped=result["stopped"], purged=result["purged"]))
        lines += [result["cron"], "", self.t("done_next")]
        while True:
            area = self.frame(None, self.t("done_title"), self.t("done_keys"))
            if area:
                top, bottom, w = area
                self.paragraph(top, 2, w - 4, bottom, "\n".join(lines))
            if self.scr.get_wch() in (*ENTER, ESC, "q", "Q"):
                return

    def run(self):
        screens = [
            self.screen_lang,
            lambda: self.screen_text(2, "intro_title", "intro_body"),
            lambda: (self.screen_text(3, "cron_title", "cron_body_docker", up=DOCKER_UP) if IN_DOCKER
                     else self.screen_text(3, "cron_title", "cron_body", line=CRON_LINE)),
            self.screen_cities,
            self.screen_finish,
        ]
        i = 0
        while True:
            result = screens[i]()
            if result == "quit":
                return None
            if result == "back":
                i = max(0, i - 1)
            elif i == len(screens) - 1:
                break
            else:
                i += 1
        result = self.apply()
        self.screen_done(result)
        return result


def main(conn):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SystemExit("setup은 터미널에서 실행하세요 (TUI)")
    os.environ.setdefault("ESCDELAY", "25")  # Esc 키 반응 지연 줄이기
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:  # LANG의 로케일이 설치 안 된 경우 (예: ko_KR 없음). 한글 출력엔 UTF-8이면 충분
        locale.setlocale(locale.LC_ALL, "C.UTF-8")
    try:
        result = curses.wrapper(lambda scr: Setup(scr, conn).run())
    except KeyboardInterrupt:
        result = None
    if result:
        print(f"accu_weather: +{result['added']} / stopped {result['stopped']} / purged {result['purged']}. "
              f"{result['cron']}")
