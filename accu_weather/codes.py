"""WMO 날씨 코드 → 카테고리 / 가중치 (weather_code.json, weather_severity.json)."""

import json

from .config import ROOT

# WMO 코드 → {category, en, ko, ja} / {x, y}
WEATHER_CODES = json.loads((ROOT / "weather_code.json").read_text(encoding="utf-8"))
SEVERITY_XY = json.loads((ROOT / "weather_severity.json").read_text(encoding="utf-8"))


def category(code):
    """WMO 코드 → 1 맑음, 2 구름/흐림, 3 안개, 4 비, 5 눈, 6 뇌우."""
    entry = WEATHER_CODES.get(str(code))
    return entry["category"] if entry else None


def weight(code):
    """WMO 코드 → 가중치 0~5 (원점~(x,y) 넓이). 모르는 코드는 0."""
    xy = SEVERITY_XY.get(str(code))
    return xy["x"] * xy["y"] / 15 * 5 if xy else 0.0


def representative(codes):
    """가중치가 가장 큰 코드가 대표 날씨 (같으면 코드 번호가 큰 쪽)."""
    codes = [c for c in codes if c is not None]
    return max(codes, key=lambda c: (weight(c), c)) if codes else None
