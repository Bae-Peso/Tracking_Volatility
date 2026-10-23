"""weather_weight.json을 정할 때 쓴 분석: 여러 기후대 도시의 1시간 예보를 받아 날씨 코드별로
이동·안전 영향(시야, 눈, 빙판, 돌풍)을 평균 낸다 (PLAN.md 5.1). 표준 라이브러리만.

python3 tools/weight_study.py [저장 폴더]   # 받은 응답을 저장 폴더에 두고, 있으면 다시 받지 않음

결과는 참고값이다. 표본이 적은 코드(어는 비, 강한 눈, 우박 뇌우 …)와 번개 위험은 판단으로 정한다.
"""

import json
import statistics as st
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOURLY = ["weather_code", "precipitation", "snowfall", "visibility", "wind_gusts_10m", "temperature_2m"]
CITIES = {
    "Seoul": (37.57, 126.98), "Busan": (35.18, 129.08), "Tokyo": (35.68, 139.69), "Osaka": (34.69, 135.50),
    "Sapporo": (43.06, 141.35), "Taipei": (25.03, 121.57),
    "Ulaanbaatar": (47.89, 106.91), "Yakutsk": (62.03, 129.73), "Anchorage": (61.22, -149.90),
    "Reykjavik": (64.15, -21.94), "Oslo": (59.91, 10.75), "Helsinki": (60.17, 24.94), "Moscow": (55.76, 37.62),
    "Montreal": (45.50, -73.57), "Denver": (39.74, -104.99),
    "San Francisco": (37.77, -122.42), "Lima": (-12.05, -77.04), "London": (51.51, -0.13),
    "Singapore": (1.35, 103.82), "Bangkok": (13.75, 100.50), "Darwin": (-12.46, 130.84), "Miami": (25.76, -80.19),
    "Sao Paulo": (-23.55, -46.63), "Mumbai": (19.08, 72.88),
}


def clamp(v):
    return max(0.0, min(1.0, v))


def factors(r):
    """한 시간의 위험 요소 (각 0~1)."""
    return (
        clamp((5000 - r["visibility"]) / 4000),  # 시야: 5km → 0, 1km 이하 → 1
        clamp(r["snowfall"] / 1.0),  # 눈: 시간당 1cm 이상 → 1
        0.5 if r["precipitation"] > 0 and r["temperature_2m"] <= 1 else 0.0,  # 0℃ 근처 강수 → 빙판 가능
        clamp((r["wind_gusts_10m"] - 30) / 40),  # 돌풍: 30km/h → 0, 70km/h 이상 → 1
    )


def hourly_rows(cache):
    cache.mkdir(parents=True, exist_ok=True)
    for name, (lat, lon) in CITIES.items():
        path = cache / f"{name}.json"
        if not path.exists():
            q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "hourly": ",".join(HOURLY),
                                        "past_days": 14, "forecast_days": 14, "timezone": "auto"})
            with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=30) as resp:
                path.write_bytes(resp.read())
            time.sleep(0.3)
        h = json.loads(path.read_text())["hourly"]
        for i in range(len(h["time"])):
            r = {k: h[k][i] for k in HOURLY}
            if all(v is not None for v in r.values()):
                yield r


def main():
    names = json.loads((ROOT / "weather_code.json").read_text(encoding="utf-8"))
    current = json.loads((ROOT / "weather_weight.json").read_text(encoding="utf-8"))
    by_code = defaultdict(list)
    for r in hourly_rows(Path(sys.argv[1] if len(sys.argv) > 1 else "weight_study")):
        by_code[r["weather_code"]].append(factors(r))
    # 위험이 하나만 커도 커지고 겹치면 더 커지게: 1 − Π(1 − 요소). 맑음(0)에도 바람은 있으니 맑음 = 0으로 맞춤
    combined = {c: st.mean(1 - (1 - v) * (1 - s) * (1 - i) * (1 - g) for v, s, i, g in fs) for c, fs in by_code.items()}
    base = combined.get(0, 0.0)
    print("코드\t이름\t시간\t시야\t눈\t빙판\t돌풍\t자료 값\t지금 가중치")
    for code in sorted(by_code):
        fs = by_code[code]
        means = [st.mean(f[i] for f in fs) for i in range(4)]
        value = clamp((combined[code] - base) / (1 - base))
        print(f"{code}\t{names[str(code)]['ko']}\t{len(fs)}\t" + "\t".join(f"{m:.2f}" for m in means)
              + f"\t{value:.2f}\t{current.get(str(code))}")


if __name__ == "__main__":
    main()
