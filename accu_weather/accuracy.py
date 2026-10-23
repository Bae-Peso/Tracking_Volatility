"""정확도: 날짜마다 n일전(1~14) 예보를 d0(당일 22시 예보, 사실상 최종값)와 비교해 한 줄씩 저장한다.

월별·연도별 정확도는 이 행들을 (도시, 월, lead_days)로 묶어 평균 낸다 (PLAN.md 5.2).
"""

import math

from . import codes, db


def _diff(a, b):
    return None if a is None or b is None else a - b


def _log_diff(a, b):
    return None if a is None or b is None else math.log1p(a) - math.log1p(b)


def score(row, cfg):
    """0~100. 항목마다 0(d0와 같음)~1(기준값 이상 차이)로 만든 뒤 가중 합을 뺀다. 값이 빠졌으면 None."""
    parts = (row["temp_max_diff"], row["temp_min_diff"], row["feel_max_diff"], row["feel_min_diff"],
             row["precip_prob_diff"], row["precip_log_diff"], row["weather_diff"])
    if any(p is None for p in parts):
        return None
    w = cfg["weights"]

    def degrees(hi, lo):  # 최고·최저 차이의 평균을 기준값으로 나눔
        return min((abs(hi) + abs(lo)) / 2 / cfg["temp_worst_c"], 1.0)

    temp = degrees(row["temp_max_diff"], row["temp_min_diff"])
    feel = degrees(row["feel_max_diff"], row["feel_min_diff"])
    prob = min(abs(row["precip_prob_diff"]) / 100.0, 1.0)
    rain = min(abs(row["precip_log_diff"]) / math.log1p(cfg["rain_worst_mm"]), 1.0)
    penalty = (w["temp"] * temp + w["feel"] * feel + w["prob"] * prob + w["rain"] * rain
               + w["weather"] * row["weather_diff"])
    return round(100 * (1 - penalty), 1)


def accuracy_rows(forecasts, cfg, computed_at):
    """한 날짜의 하루 통합 예보들(weather 행) → n일전마다 정확도 행. d0가 없으면 빈 목록."""
    by_lead = {f["lead_days"]: f for f in forecasts}
    d0 = by_lead.get(0)
    if d0 is None:
        return []
    rows = []
    for lead, f in sorted(by_lead.items()):
        if lead == 0:
            continue
        row = {
            "target_date": f["target_date"],
            "city_id": f["city_id"],
            "lead_days": lead,
            "source": f["source"],
            "weather_match": None if f["weather"] is None or d0["weather"] is None
                             else int(f["weather"] == d0["weather"]),
            "weather_diff": None if f["weather_code"] is None or d0["weather_code"] is None
                            else abs(codes.weight(f["weather_code"]) - codes.weight(d0["weather_code"])),
            "temp_max_diff": _diff(f["temp_max"], d0["temp_max"]),
            "temp_min_diff": _diff(f["temp_min"], d0["temp_min"]),
            "feel_max_diff": _diff(f["feel_max"], d0["feel_max"]),
            "feel_min_diff": _diff(f["feel_min"], d0["feel_min"]),
            "precip_prob_diff": _diff(f["precip_prob"], d0["precip_prob"]),
            "precip_log_diff": _log_diff(f["precip_mm"], d0["precip_mm"]),
            "computed_at": computed_at,
        }
        row["score"] = score(row, cfg)
        rows.append(row)
    return rows


def compute(conn, cfg, city_id, target_date, source):
    """한 도시·날짜의 정확도를 다시 계산해 저장한다. 저장한 행 수를 돌려준다."""
    rows = accuracy_rows(db.day_forecasts(conn, city_id, target_date, source), cfg["accuracy"], db.utc_now())
    db.upsert_accuracy(conn, rows)
    return len(rows)


def recompute(conn, cfg, city_id=None):
    """d0가 있는 모든 날짜를 다시 계산한다 (기준값·가중치·날씨 좌표를 바꾼 뒤)."""
    total = 0
    for r in db.d0_dates(conn, city_id):
        total += compute(conn, cfg, r["city_id"], r["target_date"], r["source"])
    return total
