# 날씨 예보 변동성 추적기 — 계획서

작성일: 2026-10-22 / 수정: 2026-10-23 (v2: 데이터 소스·DB 구조·정확도 기준 변경)
버전 : 0.01 (당초 테스트 및 계획본)

---

## 1. 목표

- 사용자가 등록한 도시들의 **15일 예보(오늘 포함 2주)를 매일 밤 22시에 수집**한다 (23시, 23시 30분은 실패 대비 재시도).
- 같은 날짜·시간대에 대해 "14일 전, 13일 전 … 당일"에 각각 뭐라고 예보했는지 쌓는다.
- 정확도는 실측과의 비교가 아니라 **예보가 얼마나 자주·크게 바뀌었는지(변동성)** 로 본다.
  → "n일 전 예보가 다음 날 바뀔 확률" 정도를 1년간 모아서 보는 것이 목적. 엄밀한 정밀도는 필요 없음.
- NAS PC에서 cron + bash + Python + SQLite로 무인 가동한다.

### v1 → v2 변경 요약

| 항목 | v1 | v2 | 비고 |
|---|---|---|---|
| 데이터 소스 | 일본 기상청(JMA) | **Open-Meteo** (wttr.in은 보조 옵션) | # 변경 이유는 예상 강우량을 획득하는데 문제가 있어서
| 시간 단위 | 하루 / 6시간 | **3시간 슬롯(00~21시) + 하루 통합** |  |
| 테이블 | 세로형 테이블 + 도시별 VIEW | **도시 / 날씨 정보 / 정확도** 3개 (검색 위주) | 사람이 보는 건 다른 툴이나 테이블로 제작할 것 |
| 정확도 | 실측값과 비교 | **예보 변동성** (실측 수집 안 함) | 정확히는 각 일자에 대한 변동성 추적 |
| 도시 | 설정 파일에 고정 | **사용자가 CLI로 추가·삭제** | 가능하다면 CUI로 관리하는 편이 바람직함 |

---

## 2. 데이터 소스: wttr.in 대신 Open-Meteo를 기본으로

wttr.in의 경우 (2026-10-23 오사카 직접 확인), **오늘·내일·모레 3일치만** 수집 가능.
그러면 최대 "2일 전 예보"까지밖에 비교가 안 되기에 장기간의 대조 및 비교가 불가능함.

| | wttr.in (`?format=j1`) | Open-Meteo |
|---|---|---|
| 예보 기간 | **3일** | **15일** 사용 (오늘 + 14일, 최대 16일. 2026-10-23 15일 전부 빈 값 없음 확인) |
| 시간 단위 | 3시간 (00~21시, 8개) | 1시간 → 3시간 슬롯으로 묶어서 사용 |
| 날씨 / 최고·최저 기온 / 바람 / 가시거리 / 강수량 / 강수확률 | 모두 있음 | 모두 있음 (확인함) |
| 도시 검색 | 이름으로 조회 가능 | 전용 지오코딩 API (**영어 이름으로 통일**, `language=en`) |
| 키 / 비용 | 없음 | 없음 (비상업 무료, 하루 1만 회 제한 → 충분) |
| 안정성 | 개인 운영 서비스라 가끔 느리거나 막힘 | API 전용 서비스 |

**결정:** Open-Meteo를 기본으로 쓴다. 수집 코드는 소스별 어댑터로 나눠서,
원하면 wttr.in도 같은 테이블에 `source='wttr'`로 함께 넣을 수 있게 한다. 이 경우 lead는 0~2일만 채워진다.
나중에 "어느 서비스 예보가 더 오락가락하나" 비교도 가능하다.

### 사용 API

```
# 예보 (도시 여러 개를 한 번에 요청 가능: latitude=34.7,35.68&longitude=135.5,139.76)
https://api.open-meteo.com/v1/forecast
  ?latitude={lat}&longitude={lon}
  &hourly=weather_code,temperature_2m,wind_speed_10m,visibility,precipitation,precipitation_probability
  &timezone=auto&forecast_days=15

# 도시 검색 (도시 추가할 때) (도시 이름은 영어로 검색, 결과의 name/country도 영어로 저장)
https://geocoding-api.open-meteo.com/v1/search?name={English name}&count=5&language=en
```

---

## 3. 수집 흐름

```
cron 22:00 / 23:00 / 23:30 → run.sh → fetch_forecast.py
  0) 오늘 22시 이후 수집분이 이미 있으면 건너뜀 (앞 실행이 성공했으면 뒤 실행은 아무것도 안 함)
  1) Open-Meteo에 15일치 요청
  2) 1시간 값 → 3시간 슬롯(00,03,…,21)으로 묶음
  3) weather 테이블에 저장
  4) (다음 단계) 3시간 슬롯 8개를 하루 통합 행(slot='day')으로 계산, 오늘 날짜의 변동성 계산 → accuracy 저장
```

### "n일 전 예보"의 정의

- `lead_days = 대상 날짜 − 수집한 날짜` (도시 현지 날짜 기준)
- 하루 한 번(22시)만 받으므로 **"n일 전 22시에 본 예보"** 가 그 칸의 값이다.
- 매시간 수집하지 않는 이유: 결국 22시 값 하나만 쓰고, Open-Meteo 예보도 몇 시간 간격으로만 갱신되므로 나머지 호출은 의미가 없다.
- 실패 대비: 23:00, 23:30 실행이 재시도 역할. 셋 다 실패한 날은 과거 예보 API로 나중에 보충 가능(강수확률·가시거리 제외).
- 당일(d0) 22시 예보는 이미 지나간 시간대에 대해서는 사실상 실측에 가깝다. 그래서 필요하면 "최종값" 기준으로 쓸 수 있다.
- 22시 전에 수동으로 실행한 값은 그날 22시 실행이 덮어쓴다.

### 하루 통합 규칙 (slot='day')

| 칼럼 | 통합 방법 |
|---|---|
| 날씨 | 8개 슬롯 중 가장 "나쁜" 카테고리 (비가 한 번이라도 있으면 비) |
| 최고 기온 / 최저 기온 | 슬롯 최고의 최대 / 슬롯 최저의 최소 |
| 바람 | 최대 |
| 가시거리 | 최소 |
| 강수량 | 합계 |
| 강수확률 | 최대 |

---

## 4. DB 구조 (SQLite, 검색 위주)

테이블 3개: **city(도시)**, **weather(날씨 정보)**, **accuracy(정확도)**.

### 4.1 city — 도시

```sql
CREATE TABLE city (
  city_id    INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,           -- 'Osaka' (영어)
  country    TEXT,                    -- 'Japan' (영어)
  latitude   REAL NOT NULL,
  longitude  REAL NOT NULL,
  timezone   TEXT NOT NULL,           -- 'Asia/Tokyo' (22시 확정 기준)
  active     INTEGER NOT NULL DEFAULT 1,
  added_at   TEXT NOT NULL,
  UNIQUE (latitude, longitude)
);
```

### 4.2 weather — 날씨 정보

요청하신 칼럼 `날짜 | 도시 | n일전 예보 | 날씨 | 최고 기온 | 최저 기온 | 바람 | 가시거리 | 강수량 | 강수확률`을 그대로 따릅니다.
여기에 3시간 슬롯과 관리용 칼럼을 추가했습니다.

```sql
CREATE TABLE weather (
  target_date  TEXT    NOT NULL,      -- 날짜 '2026-10-24'
  slot         TEXT    NOT NULL,      -- '00','03',…,'21' 또는 'day'(하루 통합)
  city_id      INTEGER NOT NULL REFERENCES city(city_id),  -- 도시
  lead_days    INTEGER NOT NULL,      -- n일전 예보 (0~14)
  weather      INTEGER,               -- 날씨 카테고리 (아래 표)
  weather_code INTEGER,               -- 소스 원본 코드 (재분류용)
  temp_max     REAL,                  -- 최고 기온 ℃
  temp_min     REAL,                  -- 최저 기온 ℃
  wind_kmh     REAL,                  -- 바람 km/h
  visibility_m REAL,                  -- 가시거리 m
  precip_mm    REAL,                  -- 강수량 mm
  precip_prob  INTEGER,               -- 강수확률 %
  source       TEXT    NOT NULL DEFAULT 'open-meteo',
  fetched_at   TEXT    NOT NULL,      -- 수집 시각
  PRIMARY KEY (city_id, target_date, slot, lead_days, source)
);
CREATE INDEX idx_weather_date ON weather (target_date, slot);
```

검색 예시:

```sql
-- 오사카 10/24 하루 예보가 14일 전부터 어떻게 변했나
SELECT lead_days, weather, temp_max, temp_min, precip_prob
FROM weather JOIN city USING (city_id)
WHERE city.name = 'Osaka' AND target_date = '2026-10-24' AND slot = 'day'
ORDER BY lead_days DESC;

-- 10/24 12시대 슬롯을 모든 도시에서 비교
SELECT city.name, lead_days, weather, precip_prob
FROM weather JOIN city USING (city_id)
WHERE target_date = '2026-10-24' AND slot = '12';
```

### 날씨 카테고리 숫자
WMO 코드 → 카테고리 매핑과 날씨 이름은 `weather_code.json` 한 파일에서 관리한다.
(`fetch_forecast.py`의 `weather_category()`는 그 전에 만든 프로토타입이며, 이 파일을 읽는 방식으로 교체한다.)
추후 기계 번역을 통해 다국어 추가 예정

```json
"61": {"category": 4, "en": "Slight rain", "ko": "약한 비"}
```

| 값 | 의미 | Open-Meteo 코드(WMO) |
|---|---|---|
| 1 | 맑음 | 0, 1 |
| 2 | 구름/흐림 | 2, 3 |
| 3 | 안개 | 45, 48 |
| 4 | 비 | 51~67, 80~82 |
| 5 | 눈 | 71~77, 85, 86 |
| 6 | 뇌우 | 95~99 |

숫자가 클수록 "나쁜" 날씨라서 하루 통합 시 최댓값을 쓰면 된다. wttr.in을 붙이면 wttr 코드용 매핑 표를 하나 더 둔다.

### 4.3 accuracy — 정확도(변동성)

대상 날짜의 확정 시점(그날 22시)에 d14~d0 하루 통합 행을 비교해서 한 줄 저장한다.

```sql
CREATE TABLE accuracy (
  target_date       TEXT    NOT NULL,
  city_id           INTEGER NOT NULL REFERENCES city(city_id),
  source            TEXT    NOT NULL DEFAULT 'open-meteo',
  n_forecasts       INTEGER,          -- 비교에 쓴 예보 개수 (최대 15)
  temp_max_range    REAL,             -- d14~d0 최고기온 (최댓값 − 최솟값)
  temp_min_range    REAL,
  temp_max_drift    REAL,             -- 각 n일전 값과 d0 값 차이의 평균
  precip_prob_range INTEGER,          -- 강수확률 (최댓값 − 최솟값), 0~100 %
  precip_log_range  REAL,             -- log1p(강수량 최댓값) − log1p(강수량 최솟값)
  weather_changes   INTEGER,          -- 하루 전 예보 대비 날씨가 바뀐 횟수 (d14→d13 … d1→d0)
  weather_change_rate REAL,           -- weather_changes / (n_forecasts − 1)
  weather_severity  REAL,             -- 0~1, 날씨 변화의 심각도 (weather_severity.json 기준, 5.1 참고)
  stability_score   REAL,             -- 0~100, 높을수록 예보가 안 바뀜
  computed_at       TEXT    NOT NULL,
  PRIMARY KEY (city_id, target_date, source)
);
```

### 4.4 용량

도시 1개당 하루 약 135행(15일 × 9슬롯)이 확정되어 **연간 약 5만 행**이 쌓인다.

---

## 5. 변동성(정확도) 계산

### 5.1 종합 점수 함수
4개 항목을 각각 0(best)~1(worst)로 만든 뒤 **0.25씩 같은 가중치**로 합친다.

- **온도**: 0℃ 차이를 best, 5℃ 이상 차이를 worst로 판단함
- **날씨**: 맑음 → 구름처럼 생활에 큰 영향이 없는 변화는 감점을 적게, 맑음 → 호우·뇌우처럼 극단적인 변화는 감점을 크게 준다.
  WMO 코드마다 평면 좌표 (x=종류 0~5, y=강도 1~3)를 `weather_severity.json`에 둔다.
  (WMO 번호의 두 자리를 그대로 쓰면 80=0점, 77 싸라기눈 > 75 강한 눈처럼 순서가 깨지므로 좌표를 직접 지정)
  - x: 0 맑음, 1 구름, 2 안개·이슬비, 3 비·소나기, 4 눈·어는 비, 5 뇌우 / y: 1 약, 2 보통, 3 강
  - 가중치 `w = x·y / 15 × 5` (원점~(x,y) 직사각형 넓이, 최대 5)
  - 두 예보 사이 감점 = `|w_a − w_b| / 5` (넓이가 이미 제곱처럼 커지므로 지수 없이 사용)
  - `weather_severity` = d14~d0 중 w 최댓값과 최솟값의 감점 (다른 항목처럼 범위 기준)
- **강우량**: 0 → 1mm와 10 → 11mm는 체감이 다르므로 **로그 척도**(`log1p(mm)`)로 차이를 잰다.
  기본값은 0mm ↔ 10mm 차이(`log1p(10)` ≈ 2.40)를 worst로 둔다.
- **강수확률**: 0~100(%) 고정 범위이므로 차이를 100으로 나눠 그대로 쓴다.

```python
def stability_score(temp_max_range, temp_min_range, precip_prob_range, precip_log_range, weather_severity):
    temp = min((temp_max_range + temp_min_range) / 2 / 5.0, 1.0)   # 평균 5℃ 이상 흔들리면 최악
    prob = min(precip_prob_range / 100.0, 1.0)
    rain = min(precip_log_range / math.log1p(10.0), 1.0)           # 0mm ↔ 10mm 이상 차이면 최악
    return round(100 * (1 - 0.25 * (temp + prob + rain + weather_severity)), 1)
```

가중치(0.25 × 4), 기준값(5℃, 10mm)은 `config.toml`, 날씨 좌표는 `weather_severity.json`에서 바꿀 수 있게 한다. 바꾼 뒤 `recompute`로 전체 재계산 가능.

### 5.2 1년 모은 뒤 볼 것 (report)

- **"n일 전 → n−1일 전에 날씨가 바뀔 확률"**: 핵심 지표

```sql
SELECT a.lead_days AS from_lead,
       AVG(a.weather <> b.weather) AS change_prob,
       AVG(ABS(a.temp_max - b.temp_max)) AS avg_temp_shift
FROM weather a
JOIN weather b ON b.city_id = a.city_id AND b.target_date = a.target_date
              AND b.slot = a.slot AND b.lead_days = a.lead_days - 1 AND b.source = a.source
WHERE a.slot = 'day'
GROUP BY a.lead_days ORDER BY a.lead_days DESC;
```

- 도시별·월별 평균 stability_score → 어느 도시, 어느 계절에 예보가 가장 오락가락하나
- 슬롯별(00~21시) 변동성 → 하루 중 어느 시간대 예보가 잘 바뀌나
- 출력은 터미널 표와 CSV. 그래프는 선택 사항.

---

## 6. 도시 관리 (사용자가 추가)

```bash
python -m accu_weather city add "Osaka"         # 영어 이름으로 검색, 후보를 번호로 보여주고 선택
python -m accu_weather city add --lat 34.70 --lon 135.50 --name "osaka"   # 좌표 직접 지정
python -m accu_weather city list
python -m accu_weather city disable 3           # 수집 중단 (데이터는 유지)
```

- 도시를 추가하면 다음 22시 수집부터 반영된다. 과거 예보는 소급할 수 없어서 추가한 날부터 쌓인다.
- 삭제는 기본적으로 `active=0` (기록 보존). 완전 삭제는 `--purge` 옵션.
- 추후 TUI로 사용자가 직접 추가하기 편한 대화형 인터페이스가 있으면 좋을 것으로 예상됨.

---

## 7. 실행/운영

### 7.1 디렉토리

```
accu_weather/
├─ PLAN.md
├─ config.toml            # 가중치, 기준값, 수집 소스 on/off
├─ run.sh                 # cron 진입점
├─ accu_weather/
│   ├─ __main__.py        # collect / city / recompute / report
│   ├─ sources/
│   │   ├─ openmeteo.py   # 요청 + 3시간 슬롯 변환
│   │   └─ wttr.py        # (선택) wttr.in 어댑터
│   ├─ db.py              # 스키마, upsert, 확정 처리
│   ├─ daily.py           # 하루 통합
│   └─ accuracy.py        # 변동성 계산
├─ data/weather.sqlite3
└─ logs/
```

의존성: Python 3.10+ 표준 라이브러리만 사용 (`urllib`, `sqlite3`, `json`, `zoneinfo`, `tomllib`(3.11+)). Rust는 불필요.

### 7.2 run.sh

`flock`으로 중복 실행 방지, `timeout 120`, 월별 로그 파일(`logs/YYYY-MM.log`)에 결과·실패 기록. (구현됨: `run.sh`)

### 7.3 crontab

```
0  22 * * *  /home/baepeso/Programming/accu_weather/run.sh
0  23 * * *  /home/baepeso/Programming/accu_weather/run.sh
30 23 * * *  /home/baepeso/Programming/accu_weather/run.sh
30 4  * * 0  sqlite3 /home/baepeso/Programming/accu_weather/data/weather.sqlite3 ".backup '/백업경로/weather-$(date +\%F).sqlite3'"
```

- cron 시각은 서버 시간대 기준이다. 서버가 KST/JST면 그대로, 다른 시간대면 `CRON_TZ=Asia/Tokyo`를 위에 추가한다.
- "오늘 이미 받았나" 판단은 스크립트가 도시 시간대(`TIMEZONE`) 기준으로 한다.
- 매 실행 결과(성공 행 수, 건너뜀, 실패)는 `logs/YYYY-MM.log`에만 기록한다. DB에 별도 로그 테이블은 두지 않는다.

---

## 8. 단계별 진행

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 1 | 스키마 + `city add/list` + Open-Meteo 수집 + 3시간 슬롯 upsert | 수동 실행으로 weather에 15일치가 들어감 |
| 2 | run.sh + crontab 등록 (22:00 / 23:00 / 23:30) | **가능한 빨리 가동** (강수확률·가시거리는 과거 데이터로 소급 불가) |
| 3 | 하루 통합 | 22시 실행 후 `slot='day'` 행 생성 |
| 4 | 변동성 계산 + accuracy | 15일 가동 후 d14~d0가 다 찬 날짜의 점수 생성 |
| 5 | report + recompute + 백업 | "n일전 → n−1일전 변경 확률" 표 출력 |
| 선택 | wttr.in 어댑터, 실제 관측값 비교 | 필요해지면 |

---

## 9. 남은 결정 사항 (기본값으로 진행해도 됨)

1. **확정 시각**: 22시 (기본) — 다른 시각을 원하면 config에서 변경
2. **하루 통합 날씨 규칙**: "가장 나쁜 날씨" (기본) vs "가장 많이 나온 날씨"
3. **첫 등록 도시**: 오사카(기존 테스트 파일 좌표 34.70, 135.50) 외에 처음부터 넣을 도시
