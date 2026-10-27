"""웹 조회용 데이터: SQLite를 읽기 전용으로 열어 화면에 쓸 값으로 바꾼다 (Flask 없이 테스트 가능).

- 달력(주·월·연)과 일간 모달: 날짜마다 n일전(1~14) 하루 통합 예보를 d0(당일 22시 예보)와 비교한 값.
  비교는 accu_weather.accuracy와 같은 함수·기준값을 쓴다 (accuracy 테이블과 같은 결과).
- 그래프: 기간 안의 1시간 슬롯 값을 1·3·6·12시간으로 묶은 값('slot') 또는 하루 통합 값('day')을 n일전(0~14)별로.
  시간 묶음과 하루 통합 값은 일간 보기와 같은 규칙(slot='day': 최고기온 최대, 최저기온 최소, 강수량 합계 …).
  3일·1주 같은 여러 날 단위는 화면(app.js)이 하루 통합 값을 묶어서 만든다.

화면 문구는 보내지 않는다 (날씨는 코드, 오류는 오류 코드). 번역은 화면의 i18n 파일이 한다.
"""

import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from accu_weather import accuracy, codes

SOURCE = "open-meteo"
LEADS = list(range(1, 15))  # 비교 대상 n일전
SERIES_MAX_DAYS = 760  # 그래프는 최대 2년 + 앞으로 14일
SERIES_HOURS = (1, 3, 6, 12)  # 그래프 시간 단위 (step='slot'일 때 몇 시간씩 묶을지)

# key: (단위, 소수 자리). 이름은 화면의 i18n 파일에 (cal.*, day.*, series.*)
# 달력 색·주간 표 (점수의 단위 "점/pts/点"도 i18n)
CALENDAR_METRICS = {
    "score": ("", 1),
    "weather": ("", 2),
    "temp_max": ("℃", 1),
    "temp_min": ("℃", 1),
    "feel_max": ("℃", 1),
    "feel_min": ("℃", 1),
    "precip_prob": ("%p", 0),
    "precip": ("mm", 1),
}
# 일간 모달 그래프·표 (d0와의 차이)
DAY_METRICS = {
    "temp_max": ("℃", 1),
    "temp_min": ("℃", 1),
    "feel_max": ("℃", 1),
    "feel_min": ("℃", 1),
    "precip_prob": ("%", 0),
    "precip": ("mm", 1),
    "wind": ("km/h", 1),
    "visibility": ("km", 1),
    "weather": ("", 2),
}
# 그래프 모드 (예보 값 그대로). weather만 값이 아니라 같은 시각 d0와의 날씨 변동성 0~1 (_weather_vs_d0)
SERIES_METRICS = {
    "temp_max": ("℃", 1),
    "temp_min": ("℃", 1),
    "feel_max": ("℃", 1),
    "feel_min": ("℃", 1),
    "precip_prob": ("%", 0),
    "precip": ("mm", 1),
    "wind": ("km/h", 1),
    "visibility": ("km", 1),
    "weather": ("", 2),
}
# 슬롯을 몇 시간씩 묶을 때 규칙 (하루 통합과 같은 규칙. 날씨는 가중치가 가장 큰 = 가장 나쁜 날씨)
WITHIN_DAY_RULE = {
    "temp_max": max, "temp_min": min, "feel_max": max, "feel_min": min, "precip": sum, "precip_prob": max, "wind": max, "visibility": min, "weather": max,
}


class RangeTooLong(ValueError):
    def __init__(self, max_days):
        super().__init__(max_days)
        self.max_days = max_days


def meta(acc_cfg):
    def table(metrics):
        return [{"key": k, "unit": v[0], "digits": v[1]} for k, v in metrics.items()]

    return {
        "leads": LEADS,
        "series_max_days": SERIES_MAX_DAYS,
        "calendar_metrics": table(CALENDAR_METRICS),
        "day_metrics": table(DAY_METRICS),
        "series_metrics": table(SERIES_METRICS),
        # 날씨 이름은 weather_code.json의 언어별 이름 그대로 (언어를 추가하면 여기 이름도 추가)
        "weather_names": {code: {k: v for k, v in entry.items() if k != "category"}
                          for code, entry in codes.WEATHER_CODES.items()},
        # 색 범례: 이 값이면 빨강 (badness 1)
        "worst": {
            "score": 50, "weather": 1, "temp_max": acc_cfg["temp_worst_c"], "temp_min": acc_cfg["temp_worst_c"],
            "feel_max": acc_cfg["temp_worst_c"], "feel_min": acc_cfg["temp_worst_c"], "precip_prob": 100, "precip": acc_cfg["rain_worst_mm"],
        },
    }


def connect_ro(path):
    """읽기 전용. 수집 컨테이너가 쓰는 순간에는 잠깐 기다린다."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def cities(conn):
    rows = conn.execute("SELECT city_id, name, country, timezone, active FROM city ORDER BY active DESC, name")
    return [dict(r) for r in rows]


def city(conn, city_id):
    row = conn.execute("SELECT city_id, name, country, timezone, active FROM city WHERE city_id = ?",
                       (city_id,)).fetchone()
    return dict(row) if row else None


def errors(conn, limit=50):
    """아직 확인 안 된(read_at 없는) 수집 실패, 최근 것부터. 웹은 읽기 전용이라 확인 표시는 브라우저에 저장한다."""
    rows = conn.execute(
        "SELECT error_id, occurred_at, message FROM error_log WHERE read_at IS NULL ORDER BY error_id DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def local_today(tz):
    return datetime.now(ZoneInfo(tz)).date().isoformat()


# ---- d0 비교 ----

def _diff(a, b, scale=1):
    return None if a is None or b is None else round((a - b) / scale, 3)


def compare(by_lead, acc_cfg, slots=None):
    """한 날짜의 n일전 하루 예보들을 d0와 비교 → {n: 차이}. 차이는 n일전 − d0 (+면 높게 예보). d0가 없으면 {}.
    slots: {n: 1시간 슬롯 행} (날씨·강수확률의 시간대별 비교, accuracy와 같음)."""
    d0 = by_lead.get(0)
    return {row["lead_days"]: _view(row, d0, by_lead[row["lead_days"]])
            for row in accuracy.accuracy_rows(list(by_lead.values()), acc_cfg, "", slots)}


def _view(row, d0, f):
    def r3(v):
        return None if v is None else round(v, 3)

    return {
        "score": row["score"],
        "weather": r3(row["weather_diff"]),
        "weather_match": row["weather_match"],
        "temp_max": r3(row["temp_max_diff"]),
        "temp_min": r3(row["temp_min_diff"]),
        "feel_max": r3(row["feel_max_diff"]),
        "feel_min": r3(row["feel_min_diff"]),
        "precip_prob": row["precip_prob_diff"],
        "precip_prob_hourly": r3(row["precip_prob_hourly_diff"]),
        "precip": _diff(f["precip_mm"], d0["precip_mm"]),
        "precip_sqrt": r3(row["precip_sqrt_diff"]),
        "wind": _diff(f["wind_kmh"], d0["wind_kmh"]),
        "visibility": _diff(f["visibility_m"], d0["visibility_m"], 1000),
    }


def badness(metric, c, acc_cfg):
    """0(d0와 같음) ~ 1(기준값 이상 차이). 점수는 100점 → 0, 50점 이하 → 1."""
    if metric == "score":
        v = None if c["score"] is None else (100 - c["score"]) / 50
    elif metric == "weather":
        v = c["weather"]
    elif metric in ("temp_max", "temp_min", "feel_max", "feel_min"):
        v = None if c[metric] is None else abs(c[metric]) / acc_cfg["temp_worst_c"]
    elif metric == "precip_prob":  # 점수와 같은 값: 하루 최대 차이와 시간대별 차이를 섞음
        v = None if c["precip_prob"] is None else accuracy.mix(abs(c["precip_prob"]), c["precip_prob_hourly"], acc_cfg) / 100
    elif metric == "precip":
        v = None if c["precip_sqrt"] is None else abs(c["precip_sqrt"]) / math.sqrt(acc_cfg["rain_worst_mm"])
    else:
        raise ValueError(metric)
    return None if v is None else round(max(0.0, min(1.0, v)), 3)


def _day_forecasts(conn, city_id, start, end):
    """{target_date: {lead_days: 하루 통합 행}}"""
    by_date = defaultdict(dict)
    rows = conn.execute(
        "SELECT * FROM weather WHERE city_id = ? AND slot = 'day' AND source = ? AND target_date BETWEEN ? AND ?",
        (city_id, SOURCE, start, end),
    )
    for r in rows:
        by_date[r["target_date"]][r["lead_days"]] = r
    return by_date


def _slot_forecasts(conn, city_id, start, end):
    """{target_date: {lead_days: [1시간 슬롯 행]}} (날씨·강수확률 비교에 쓰는 열만)."""
    by_date = defaultdict(lambda: defaultdict(list))
    rows = conn.execute(
        "SELECT target_date, lead_days, slot, weather_code, precip_prob FROM weather "
        "WHERE city_id = ? AND slot != 'day' AND source = ? AND target_date BETWEEN ? AND ?",
        (city_id, SOURCE, start, end),
    )
    for r in rows:
        by_date[r["target_date"]][r["lead_days"]].append(r)
    return by_date


def _d0_value(metric, d0):
    """주간 표 '당일' 열에 보여줄 실제 예보 값. 점수·날씨 변동성은 기준 자신이라 없음."""
    return {"temp_max": d0["temp_max"], "temp_min": d0["temp_min"], "feel_max": d0["feel_max"],
            "feel_min": d0["feel_min"], "precip_prob": d0["precip_prob"], "precip": d0["precip_mm"]}.get(metric)


def calendar(conn, city_id, start, end, metric, acc_cfg):
    """달력용: d0가 있는 날짜마다 1~14일전의 값(차이 또는 점수)과 색 정도(0~1), 그리고 당일 예보 요약.
    없는 n일전은 None."""
    if metric not in CALENDAR_METRICS:
        raise ValueError(metric)
    days = {}
    slots = _slot_forecasts(conn, city_id, start, end)
    for target, by_lead in _day_forecasts(conn, city_id, start, end).items():
        d0 = by_lead.get(0)
        if d0 is None:
            continue
        compared = compare(by_lead, acc_cfg, slots.get(target))
        values, bad = [], []
        for lead in LEADS:
            c = compared.get(lead)
            if c is None:
                values.append(None)
                bad.append(None)
                continue
            values.append(c[metric])
            bad.append(badness(metric, c, acc_cfg))
        days[target] = {
            "values": values,
            "bad": bad,
            "d0": {"weather_code": d0["weather_code"], "temp_max": d0["temp_max"],
                   "temp_min": d0["temp_min"], "value": _d0_value(metric, d0)},
        }
    return days


def day(conn, city_id, target, acc_cfg):
    """일간 모달: 14일전 → 당일 순으로 예보 값, d0와의 차이, 점수. d0가 없으면 차이는 None."""
    by_lead = _day_forecasts(conn, city_id, target, target).get(target, {})
    compared = compare(by_lead, acc_cfg, _slot_forecasts(conn, city_id, target, target).get(target))
    d0 = by_lead.get(0)
    leads = []
    for lead in range(14, -1, -1):
        f = by_lead.get(lead)
        if f is None:
            leads.append({"lead": lead, "available": False})
            continue
        if d0 is None:
            c = None
        elif lead == 0:  # 기준 자신: 차이 0
            c = {**{k: 0 for k in DAY_METRICS}, "weather_match": 1, "score": None}
        else:
            c = compared[lead]
        leads.append({
            "lead": lead,
            "available": True,
            "weather_code": f["weather_code"],
            "values": {
                "temp_max": f["temp_max"], "temp_min": f["temp_min"], "feel_max": f["feel_max"],
                "feel_min": f["feel_min"], "precip_prob": f["precip_prob"],
                "precip": f["precip_mm"], "wind": f["wind_kmh"],
                "visibility": None if f["visibility_m"] is None else round(f["visibility_m"] / 1000, 2),
                "weather": None,  # 날씨는 값 자체가 없다. d0와 비교한 변동성(diffs)만
            },
            "diffs": None if c is None else {k: c[k] for k in DAY_METRICS},
            "weather_match": None if c is None else c["weather_match"],
            "score": None if c is None else c["score"],
        })
    return {
        "date": target,
        "has_d0": d0 is not None,
        "d0_weather_code": d0["weather_code"] if d0 is not None else None,
        "leads": leads,
    }


# ---- 그래프 ----

def _slot_value(metric, r):
    if metric == "precip":
        return r["precip_mm"]
    if metric == "wind":
        return r["wind_kmh"]
    if metric == "visibility":
        return None if r["visibility_m"] is None else r["visibility_m"] / 1000
    if metric == "weather":
        return None if r["weather_code"] is None else codes.weight(r["weather_code"])
    return r[metric]


def series(conn, city_id, start, end, metric, step, hours=1):
    """{daily, leads: {n: [[x, 값], …]}}. x는 슬롯이면 묶음 시작 'YYYY-MM-DDTHH:00', 하루 단위면 'YYYY-MM-DD'.
    step: 'slot'(1시간 슬롯을 hours시간씩 묶음) / 'day'(하루 통합 행). 묶는 규칙은 둘 다 WITHIN_DAY_RULE
    (최고기온 최대, 최저기온 최소, 강수량 합계, 강수확률·바람 최대, 가시거리 최소 — 일간 보기와 같은 값)."""
    if metric not in SERIES_METRICS or step not in ("slot", "day") or hours not in SERIES_HOURS:
        raise ValueError(metric if metric not in SERIES_METRICS else step if step not in ("slot", "day") else hours)
    daily = step == "day"
    rows = conn.execute(
        "SELECT * FROM weather WHERE city_id = ? AND slot " + ("= 'day'" if daily else "!= 'day'")
        + " AND source = ? AND target_date BETWEEN ? AND ? AND lead_days BETWEEN 0 AND 14 ORDER BY target_date, slot",
        (city_id, SOURCE, start, end),
    )
    groups = defaultdict(dict)  # n일전 → {x: [값, …]} (행이 시각 순이라 x도 시각 순)
    for r in rows:
        v = _slot_value(metric, r)
        x = r["target_date"] if daily else f"{r['target_date']}T{int(r['slot']) // hours * hours:02d}:00"
        values = groups[r["lead_days"]].setdefault(x, [])
        if v is not None:
            values.append(v)
    rule = WITHIN_DAY_RULE[metric]
    agg = {n: {x: rule(vs) if vs else None for x, vs in xs.items()} for n, xs in sorted(groups.items())}
    if metric == "weather":
        agg = _weather_vs_d0(agg)
    leads = {str(n): [[x, None if v is None else round(v, 3)] for x, v in xs.items()] for n, xs in agg.items()}
    return {"daily": daily, "leads": leads}


def _weather_vs_d0(agg):
    """날씨 가중치(묶음의 최댓값) → 같은 시각 d0와의 변동성 |n일전 − d0| (accuracy와 같은 식).
    d0 자신의 선은 없고, d0가 아직 없는 시각(수집 2일째 전)은 점이 없다."""
    d0 = agg.pop(0, {})
    return {n: {x: abs(v - d0[x]) for x, v in xs.items() if v is not None and d0.get(x) is not None}
            for n, xs in agg.items()}


def clamp_range(start, end, max_days=400):
    """날짜 문자열 검사. 순서가 바뀌었으면 바꾸고, 너무 길면 RangeTooLong."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    if e < s:
        s, e = e, s
    if (e - s).days + 1 > max_days:
        raise RangeTooLong(max_days)
    return s.isoformat(), e.isoformat()
