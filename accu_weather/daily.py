"""1시간 슬롯 24개 → 하루 통합 행(slot='day')."""

from collections import defaultdict

from . import codes


def _values(rows, col):
    return [r[col] for r in rows if r[col] is not None]


def day_rows(slot_rows):
    """같은 (도시, 날짜, lead_days, 소스)의 슬롯 행들을 하루 한 줄로 합친다."""
    groups = defaultdict(list)
    for r in slot_rows:
        groups[(r["city_id"], r["target_date"], r["lead_days"], r["source"])].append(r)

    rows = []
    for (city_id, target_date, lead_days, source), slots in groups.items():
        code = codes.representative(r["weather_code"] for r in slots)
        temp_max = _values(slots, "temp_max")
        temp_min = _values(slots, "temp_min")
        wind = _values(slots, "wind_kmh")
        vis = _values(slots, "visibility_m")
        precip = _values(slots, "precip_mm")
        prob = _values(slots, "precip_prob")
        rows.append({
            "target_date": target_date,
            "slot": "day",
            "city_id": city_id,
            "lead_days": lead_days,
            "weather": codes.category(code),
            "weather_code": code,
            "temp_max": max(temp_max) if temp_max else None,
            "temp_min": min(temp_min) if temp_min else None,
            "wind_kmh": max(wind) if wind else None,
            "visibility_m": min(vis) if vis else None,
            "precip_mm": round(sum(precip), 2) if precip else None,
            "precip_prob": max(prob) if prob else None,
            "source": source,
            "fetched_at": max(r["fetched_at"] for r in slots),
        })
    return rows
