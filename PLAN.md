# 날씨 예보 변동성 추적기 — 계획서

작성일: 2026-10-22 / 수정: 2026-10-23
- v2: 데이터 소스·DB 구조·정확도 기준 변경
- v3: 도시별 현지 22시 수집(cron 30분 간격), city_id UUID
- v4: 정확도를 "날짜 × n일전" 한 줄씩(d0와 비교)으로 바꾸고 월별·연도별로 n일전끼리 평균, error_log 추가
- v5: 설치 TUI(`setup`, 도시 추가·등록 취소), 백업 방향(rsync / 클라우드), 조회 단위(일별 / 주·월·연 평균)

버전 : 0.3 (1~4단계 + recompute + 설치 TUI)

---

## 1. 목표

- 사용자가 등록한 도시들의 **15일 예보(오늘 포함 2주)를 매일 각 도시 현지 시각 22시에 수집**한다 (22:30~23:30은 실패 대비 재시도).
- 같은 날짜·시간대에 대해 "14일 전, 13일 전 … 당일"에 각각 뭐라고 예보했는지 쌓는다.
- 정확도는 실측과의 비교가 아니라 **예보가 얼마나 자주·크게 바뀌었는지(변동성)** 로 본다.
  → "n일 전 예보가 다음 날 바뀔 확률" 정도를 1년간 모아서 보는 것이 목적. 엄밀한 정밀도는 필요 없음.
- NAS PC에서 cron + bash + Python + SQLite로 무인 가동한다.
- SQLite의 사용 이유는 `https://minitistics.tistory.com/48` 를 참조하여 적합하다 판단함.

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
cron 30분마다 → run.sh → python3 -m accu_weather collect
  0) active=1인 도시마다 city.timezone으로 현지 시각 계산
     → 현지 22:00~23:59가 아니거나, 현지 오늘 22시 이후 수집분이 이미 있으면 그 도시는 건너뜀
     (대상 도시가 없으면 API 호출 없이 종료)
  1) 대상 도시들을 Open-Meteo에 15일치 요청 (여러 도시를 한 번에 요청 가능)
  2) 1시간 값 → 3시간 슬롯(00,03,…,21)으로 묶음
  3) 3시간 슬롯 8개를 하루 통합 행(slot='day')으로 계산
  4) weather 테이블에 저장 (도시당 슬롯 120행 + 하루 통합 15행)
  5) 오늘 날짜(d0를 방금 받은 날짜)의 n일전 정확도 계산 → accuracy 저장
  (요청 실패 시 error_log에 기록하고 종료, 다음 30분 실행이 재시도)
```

### "n일 전 예보"의 정의

- `lead_days = 대상 날짜 − 수집한 날짜` (도시 현지 날짜 기준)
- 도시마다 하루 한 번(현지 22시)만 받으므로 **"n일 전 현지 22시에 본 예보"** 가 그 칸의 값이다.
- 매시간 수집하지 않는 이유: 결국 22시 값 하나만 쓰고, Open-Meteo 예보도 몇 시간 간격으로만 갱신되므로 나머지 호출은 의미가 없다.
- 실패 대비: 현지 22:30, 23:00, 23:30 실행이 재시도 역할. 넷 다 실패한 날은 과거 예보 API로 나중에 보충 가능(강수확률·가시거리 제외).
- 날짜·슬롯은 도시 현지 기준으로 저장한다. 사용자 시간대 변환은 웹 조회 화면에서만 한다 (7.5).
- 당일(d0) 22시 예보는 이미 지나간 시간대에 대해서는 사실상 실측에 가깝다. 그래서 필요하면 "최종값" 기준으로 쓸 수 있다.
- 22시 전에 수동으로 실행한 값은 그날 22시 실행이 덮어쓴다.

### 하루 통합 규칙 (slot='day')

| 칼럼 | 통합 방법 |
|---|---|
| 날씨 | 8개 슬롯 중 `weather_severity.json` 가중치가 가장 큰 코드 (3시간 슬롯 대표 날씨와 같은 규칙) |
| 최고 기온 / 최저 기온 | 슬롯 최고의 최대 / 슬롯 최저의 최소 |
| 바람 | 최대 |
| 가시거리 | 최소 |
| 강수량 | 합계 |
| 강수확률 | 최대 |

---

## 4. DB 구조 (SQLite, 검색 위주)

테이블 4개: **city(도시)**, **weather(날씨 정보)**, **accuracy(정확도)**, **error_log(수집 실패)**.

### 4.1 city — 도시

```sql
CREATE TABLE city (
  city_id    TEXT PRIMARY KEY,        -- uuid4
  name       TEXT NOT NULL,           -- 'Osaka' (영어)
  country    TEXT,                    -- 'Japan' (영어)
  latitude   REAL NOT NULL,           -- 소수 둘째 자리(약 1km)로 반올림해서 저장
  longitude  REAL NOT NULL,
  timezone   TEXT NOT NULL,           -- 'Asia/Tokyo' (현지 22시 확정 기준)
  active     INTEGER NOT NULL DEFAULT 1,
  added_at   TEXT NOT NULL,
  UNIQUE (latitude, longitude)
);
```

- PK는 의미 없는 UUID로 둔다. 이름·좌표를 고쳐도 키가 그대로이고, `cities.txt`로 내보내고 다른 DB에 불러와도 같은 도시로 연결된다.
- 사람이 읽는 건 `JOIN city`로 `name`을 본다. CLI에서는 UUID 앞 8자리만 입력해도 된다.

### 4.2 weather — 날씨 정보

요청하신 칼럼 `날짜 | 도시 | n일전 예보 | 날씨 | 최고 기온 | 최저 기온 | 바람 | 가시거리 | 강수량 | 강수확률`을 그대로 따릅니다.
여기에 3시간 슬롯과 관리용 칼럼을 추가했습니다.

```sql
CREATE TABLE weather (
  target_date  TEXT    NOT NULL,      -- 날짜 '2026-10-24'
  slot         TEXT    NOT NULL,      -- '00','03',…,'21' 또는 'day'(하루 통합)
  city_id      TEXT    NOT NULL REFERENCES city(city_id),  -- 도시 (uuid)
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
  fetched_at   TEXT    NOT NULL,      -- 수집 시각 (UTC, 도시끼리 비교 가능하게)
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
(`accu_weather/codes.py`가 이 파일을 읽는다.)
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

숫자가 클수록 "나쁜" 날씨다. 대표 날씨는 카테고리 최댓값이 아니라 `weather_severity.json` 가중치로 고른다 (3장 하루 통합 규칙).
wttr.in을 붙이면 wttr 코드용 매핑 표를 하나 더 둔다.

### 4.3 accuracy — 정확도

**날짜 하나에 n일전(1~14)마다 한 줄**: "n일 전에 본 이 날짜의 예보가 d0와 얼마나 같았나".

- **기준(정답 대신)**: d0 = 당일 현지 22시 예보. 이미 지나간 시간대는 사실상 실측이라 최종값으로 쓴다.
- 날짜마다 최대 14줄. 수집 실패로 빠진 n일전 예보는 그 줄만 없다. d0가 없는 날은 계산하지 않는다.
- 그 날짜의 d0를 받는 순간(현지 22시 수집 직후) 계산한다. `recompute`로 전체 재계산 가능.
- 차이는 **부호를 남긴다** (n일전 − d0). +면 높게 예보한 것. 평균 오차를 볼 때는 `ABS()`.

```sql
CREATE TABLE accuracy (
  target_date      TEXT    NOT NULL,      -- 대상 날짜 (도시 현지)
  city_id          TEXT    NOT NULL REFERENCES city(city_id),
  lead_days        INTEGER NOT NULL,      -- 1~14
  source           TEXT    NOT NULL DEFAULT 'open-meteo',
  weather_match    INTEGER,               -- 날씨 카테고리가 d0와 같으면 1, 다르면 0
  weather_severity REAL,                  -- |w − w(d0)| / 5, 0~1 (5.1)
  temp_max_diff    REAL,                  -- n일전 − d0 ℃
  temp_min_diff    REAL,
  precip_prob_diff INTEGER,               -- n일전 − d0 %p
  precip_log_diff  REAL,                  -- log1p(n일전 mm) − log1p(d0 mm)
  score            REAL,                  -- 0~100, 높을수록 d0와 가까움 (5.1)
  computed_at      TEXT    NOT NULL,
  PRIMARY KEY (city_id, target_date, lead_days, source)
);
```

### 4.4 error_log — 수집 실패 기록

```sql
CREATE TABLE error_log (
  error_id    INTEGER PRIMARY KEY,
  occurred_at TEXT NOT NULL,             -- UTC
  message     TEXT NOT NULL,             -- 'fetch failed (Osaka): HTTP Error 503 …'
  read_at     TEXT                       -- NULL이면 아직 확인 안 함
);
```

- 수집 실패(Open-Meteo 요청 실패, 예상 못 한 오류)를 남긴다. 로그 파일에도 같이 남는다.
- 웹에서 `read_at IS NULL`인 것만 알림으로 보여주고, 확인하면 `read_at`을 채운다. 행은 지우지 않는다.
- run.sh 단계 실패(`timeout`으로 강제 종료 등)는 Python이 기록할 틈이 없어 로그 파일에만 남는다.

### 4.5 용량

도시 1개당 하루 weather 135행(15일 × 9슬롯) + accuracy 14행 → **연간 약 5만 5천 행**.

---

## 5. 정확도 계산과 분석

### 5.1 한 줄(n일전 예보 하나)의 점수

4개 항목을 각각 0(d0와 같음)~1(기준값 이상 차이)로 만든 뒤 **0.25씩 같은 가중치**로 합친다.

- **온도**: 최고·최저 기온 차이의 평균. 0℃ 차이를 best, 5℃ 이상 차이를 worst로 판단함
- **날씨**: 맑음 → 구름처럼 생활에 큰 영향이 없는 변화는 감점을 적게, 맑음 → 호우·뇌우처럼 극단적인 변화는 감점을 크게 준다.
  WMO 코드마다 평면 좌표 (x=종류 0~5, y=강도 1~3)를 `weather_severity.json`에 둔다.
  (WMO 번호의 두 자리를 그대로 쓰면 80=0점, 77 싸라기눈 > 75 강한 눈처럼 순서가 깨지므로 좌표를 직접 지정)
  - x: 0 맑음, 1 구름, 2 안개·이슬비, 3 비·소나기, 4 눈·어는 비, 5 뇌우 / y: 1 약, 2 보통, 3 강
  - 가중치 `w = x·y / 15 × 5` (원점~(x,y) 직사각형 넓이, 최대 5)
  - `weather_severity = |w(n일전) − w(d0)| / 5` (넓이가 이미 제곱처럼 커지므로 지수 없이 사용)
  - `weather_match`는 카테고리만 본다 (약한 비 ↔ 강한 비도 "비"로 같음). 정도의 차이는 `weather_severity`가 반영한다.
- **강우량**: 0 → 1mm와 10 → 11mm는 체감이 다르므로 **로그 척도**(`log1p(mm)`)로 차이를 잰다.
  기본값은 0mm ↔ 10mm 차이(`log1p(10)` ≈ 2.40)를 worst로 둔다.
- **강수확률**: 0~100(%) 고정 범위이므로 차이를 100으로 나눠 그대로 쓴다.

```python
def score(row):   # accu_weather/accuracy.py
    temp = min((abs(temp_max_diff) + abs(temp_min_diff)) / 2 / 5.0, 1.0)
    prob = min(abs(precip_prob_diff) / 100.0, 1.0)
    rain = min(abs(precip_log_diff) / math.log1p(10.0), 1.0)
    return round(100 * (1 - (0.25 * temp + 0.25 * prob + 0.25 * rain + 0.25 * weather_severity)), 1)
```

가중치(0.25 × 4), 기준값(5℃, 10mm)은 `config.toml`의 `[accuracy]`, 날씨 좌표는 `weather_severity.json`에서 바꾼다.
바꾼 뒤 `python3 -m accu_weather recompute`로 전체 재계산.

### 5.2 일별·주별·월별·연도별 분석 (핵심)

| 단위 | 보는 방법 |
|---|---|
| 일별 | **조회**. 그 날짜의 accuracy 행(1~14일전)을 그대로 본다 (평균 없음) |
| 주별 | **평균**. 같은 주(ISO 주, 월요일 시작: `strftime('%G-W%V', target_date)`)의 같은 n일전끼리 |
| 월별 | **평균**. `strftime('%Y-%m', target_date)` |
| 연도별 | **평균**. `strftime('%Y', target_date)` |

같은 n일전끼리 묶어 평균 낸다. 예: 11월의 14일전 정확도 = 11/1~11/30 각 날짜에 대한 14일전 예보 30줄의 평균.
→ **도시 × 기간 × n일전(1~14)** 마다 값 하나. 한 기간에 14개, "며칠 전 예보부터 믿을 만한가" 곡선이 된다.

```sql
-- 일별: 오사카 11/1 에 대한 14일전 ~ 1일전 예보가 d0와 얼마나 같았나
SELECT lead_days, weather_match, temp_max_diff, precip_prob_diff, score
FROM accuracy JOIN city USING (city_id)
WHERE city.name = 'Osaka' AND target_date = '2026-11-01'
ORDER BY lead_days DESC;
```

```sql
-- 도시·월·n일전별 평균 (주별은 strftime('%G-W%V', …), 연도별은 strftime('%Y', …) 로 바꾸면 됨)
SELECT city.name, strftime('%Y-%m', target_date) AS month, lead_days,
       COUNT(*)                               AS days,          -- 평균에 쓴 날짜 수 (빠진 날 확인용)
       ROUND(AVG(score), 1)                   AS avg_score,
       ROUND(AVG(weather_match) * 100, 1)     AS weather_match_pct,
       ROUND(AVG(ABS(temp_max_diff)), 2)      AS temp_max_err,  -- 평균 오차 ℃
       ROUND(AVG(temp_max_diff), 2)           AS temp_max_bias, -- +면 높게 예보하는 경향
       ROUND(AVG(ABS(precip_prob_diff)), 1)   AS precip_prob_err
FROM accuracy JOIN city USING (city_id)
GROUP BY city_id, month, lead_days
ORDER BY city.name, month, lead_days;
```

- 수집 실패로 빠진 날은 그 n일전 평균에서만 빠진다. `days`가 너무 적은 칸은 걸러서 본다.

보조 지표 (weather 테이블에서 바로):

- **"n일 전 → n−1일 전에 날씨가 바뀔 확률"**: 예보가 하루 사이에 얼마나 자주 뒤집히나

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

- 슬롯별(00~21시) 변동성 → 하루 중 어느 시간대 예보가 잘 바뀌나 (필요하면 accuracy를 슬롯 단위로도 계산)
- 출력은 웹 조회 화면에서 한다 (7.5). CLI 조회 명령은 두지 않는다. 그 전까지는 `sqlite3 -readonly` 나 DB 뷰어로 직접 본다.

---

## 6. 설치와 도시 관리

### 6.1 설치 TUI

```bash
python3 -m accu_weather setup
```

표준 라이브러리 `curses`로 만든 설치 화면. 마지막 "설치"에서 Enter를 누르기 전에는 DB와 crontab을 건드리지 않는다.

| 순서 | 화면 | 내용 |
|---|---|---|
| 1 | 언어 | 한국어 / English / 日本語 (설치 화면에만 적용, 기본값은 `$LANG`). 고르는 동안 바로 그 언어로 바뀜 |
| 2 | 소개 | 프로그램 개요 |
| 3 | 자동 실행 안내 | crontab에 30분 간격 줄이 들어간다는 것, 해제 방법 |
| 4 | 도시 추가 | 영어 이름으로 검색 → "도시, 지역, 국가" 목록에서 Enter로 추가. 1개 이상이면 [다음] 표시. 등록된 도시 등록 취소 |
| 5 | 설치 | 추가할 도시, 등록 취소할 도시, crontab 줄 확인 → Enter로 적용 + `./run.sh install` |
| - | 완료 | 결과 표시 (웹 조회를 만들면 접속 주소·포트도 여기서 안내) |

- 도시 화면 키
  - Tab: 칸 이동 (검색 / 결과 / 선택 목록 / 다음)
  - Enter: 검색창에서는 검색, 결과 목록에서는 추가
  - Del: 선택 목록에서 새로 고른 도시는 빼기. 이미 등록된 도시는 등록 취소 방법을 묻는다
    → **1 수집 중단**(데이터 유지, `city disable`과 같음) / **2 완전 삭제**(데이터까지, `--purge`와 같음) / 다른 키는 취소.
    표시된 도시에서 다시 Del을 누르면 표시 해제. 실제 적용은 설치 화면에서 Enter를 누를 때.
  - Esc: 검색어가 있거나 목록에 있으면 → 검색창을 비우고 검색창으로. 빈 검색창에서 한 번 더 → 이전 화면.
- 이미 등록된 도시는 "(등록됨)" / "(수집 중단됨)"으로 함께 보인다. 같은 좌표는 두 번 고를 수 없다.
- 소개 화면에 조회 단위를 안내한다: 일별은 그대로 조회, 주별·월별·연도별은 같은 n일전끼리 평균 (5.2, 웹에서 볼 예정).
- 설치 화면 문구는 `accu_weather/setup_text.py` 에 언어별로 모아 둔다. 언어 추가는 같은 키로 한 벌 더 넣으면 된다.
- 창이 60×18보다 작으면 넓혀 달라는 안내만 띄운다. `LANG`의 로케일이 설치 안 돼 있으면 C.UTF-8로 대신 연다.

### 6.2 도시 관리 명령

```bash
python3 -m accu_weather city add "Osaka"        # 영어 이름으로 검색, 후보를 번호로 보여주고 선택
python3 -m accu_weather city add "Osaka" --lat 34.70 --lon 135.50   # 좌표 직접 지정 (시간대 자동)
python3 -m accu_weather city list [--all]
python3 -m accu_weather city disable 91f0686a   # 수집 중단 (데이터는 유지), --purge 면 완전 삭제
python3 -m accu_weather city enable 91f0686a
python3 -m accu_weather city export / import    # cities.txt (탭 구분, city_id 포함)
```

- 도시를 추가하면 그 도시의 다음 현지 22시 수집부터 반영된다. 과거 예보는 소급할 수 없어서 추가한 날부터 쌓인다.
- 삭제는 기본적으로 `active=0` (기록 보존). 완전 삭제는 `--purge` 옵션 (확인 후 삭제).
- 도시 목록은 `city export`로 `cities.txt`에 저장하고 `city import`로 불러온다. city_id가 같이 저장되므로 DB를 새로 만들어도 같은 도시로 이어진다.

---

## 7. 실행/운영

### 7.1 디렉토리

```
accu_weather/
├─ PLAN.md
├─ config.toml            # 수집 시각·기간, 정확도 가중치·기준값, 경로
├─ run.sh                 # cron 진입점
├─ cities.txt             # city export/import 파일
├─ weather_code.json      # WMO 코드 → 카테고리, 이름
├─ weather_severity.json  # WMO 코드 → (x, y) 좌표
├─ accu_weather/
│   ├─ __main__.py        # setup / collect / recompute / city
│   ├─ setup_tui.py       # 설치 TUI (curses)
│   ├─ setup_text.py      # 설치 TUI 문구 (ko / en / ja)
│   ├─ config.py          # config.toml 읽기
│   ├─ codes.py           # 카테고리, 가중치, 대표 날씨
│   ├─ collect.py         # 현지 22시가 지난 도시 골라서 수집
│   ├─ sources/
│   │   ├─ openmeteo.py   # 요청 + 3시간 슬롯 변환 + 도시 검색
│   │   └─ wttr.py        # (선택) wttr.in 어댑터
│   ├─ db.py              # 스키마, 도시, upsert
│   ├─ daily.py           # 하루 통합
│   └─ accuracy.py        # n일전 vs d0 정확도
├─ tests/                 # python3 -m unittest (네트워크 안 씀)
├─ data/weather.sqlite3
└─ logs/
```

의존성: Python 3.11+ 표준 라이브러리만 사용 (`urllib`, `sqlite3`, `json`, `zoneinfo`, `tomllib`(3.11+), `curses`). Rust는 불필요.

### 7.2 run.sh

`flock`으로 중복 실행 방지, `timeout 120`, 월별 로그 파일(`logs/YYYY-MM.log`)에 결과·실패 기록. (구현됨: `run.sh`)
받을 도시가 없는 실행은 아무것도 기록하지 않는다 (30분마다 로그가 쌓이지 않게).

### 7.3 crontab

```
*/30 * * * *  /home/baepeso/Programming/accu_weather/run.sh
```

- 수집 줄은 `./run.sh install`로 등록, `./run.sh uninstall`로 제거한다 (run.sh 줄만 교체, 다른 crontab 줄은 유지).
- 수집 cron은 서버 시간대와 상관없이 30분마다 돈다. 어느 도시를 받을지는 스크립트가 `city.timezone` 기준으로 판단한다.
  → 도시를 추가·삭제해도 crontab은 그대로, 서머타임도 `zoneinfo`가 처리.
- 날짜·슬롯·lead_days, "오늘 이미 받았나" 판단 모두 각 도시의 `city.timezone` 기준.
- 매 실행 결과(저장 행 수, 실패)는 `logs/YYYY-MM.log`에 기록한다. 실패는 `error_log` 테이블에도 남긴다 (4.4).
- 수집 실패 알림(메일·메신저)은 두지 않는다. 웹 조회를 만들면 `error_log`의 미확인 항목을 알림으로 보여준다.

### 7.4 백업 (방향만 정함)

- **시점**: 수집이 실제로 저장한 실행 뒤에 한다 (도시마다 현지 22시가 달라서 고정 시각 대신 "저장 직후").
  run.sh에서 collect가 저장한 경우에만 이어서 백업을 돌린다.
- **방법**: 먼저 `sqlite3 data/weather.sqlite3 ".backup ..."`으로 일관된 사본을 만들고 (쓰는 중인 파일을 그대로 복사하지 않음), 그 사본을
  - 다른 드라이브·NAS 공유 폴더로 `rsync`, 또는
  - 가능하면 클라우드 저장소로 업로드 (예: `rclone`).
- 정할 것: 백업 위치, 보관 개수(예: 최근 n개만), 클라우드 사용 여부.

### 7.5 웹 조회 (예정)

- nginx로 HTTP 포트를 열고, 뒤에서 **Flask** 앱이 SQLite를 **읽기 전용**으로 조회해 보여준다. 수집(쓰기)은 지금처럼 cron만 한다.
- "표준 라이브러리만" 원칙은 수집 쪽(`accu_weather/`)에만 적용한다. Flask는 웹 앱에만 쓴다.
- 기존 코드는 그대로 두고 웹 앱을 옆에 추가한다. 기존 코드에 필요한 변경은 WAL 모드 한 줄 정도.
- 공개 범위(집 안 / 외부, 인증), 웹에서 도시 관리 여부는 웹을 만들 때 정한다.
- 화면 후보: 일별 조회(그 날짜의 d14 → d0 예보와 n일전별 정확도), 주별·월별·연도별 n일전별 평균(5.2), "n일 전 → n−1일 전 변경 확률".
- `error_log`의 미확인 항목을 알림으로 보여주고, 확인하면 `read_at`을 채운다 (4.4).
- 웹을 만들면 설치 TUI 완료 화면에 접속 주소·포트를 안내하고, 포트 설정 단계를 추가한다.
- 날씨는 숫자 대신 `weather_code.json` 이름으로, 시간은 도시 현지 기준(필요하면 보는 사람 시간대로 변환)으로 보여준다.
- 웹과 cron이 동시에 DB를 쓰므로 SQLite를 WAL 모드로 바꿔 읽기가 쓰기를 막지 않게 한다.

---

## 8. 단계별 진행

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 1 | ✅ 스키마 + `city add/list` + Open-Meteo 수집 + 3시간 슬롯 upsert | 수동 실행으로 weather에 15일치가 들어감 |
| 2 | ✅ run.sh + crontab 등록 (`./run.sh install`, 30분 간격, 도시별 현지 22시 판단) | **가능한 빨리 가동** (강수확률·가시거리는 과거 데이터로 소급 불가) |
| 3 | ✅ 하루 통합 | 22시 실행 후 `slot='day'` 행 생성 |
| 4 | 정확도 (n일전 vs d0) + error_log + 테스트 | ✅ 구현. 가동 다음 날부터 1일전 행이 생기고, 15일 뒤 1~14일전이 다 참 |
| 5 | recompute ✅ + 설치 TUI ✅ + 백업 (7.4) | 백업 위치 정하고 run.sh에 연결 |
| 6 | 웹 조회 (nginx + Flask, 7.5, 보류) | 브라우저에서 "n일전 → n−1일전 변경 확률" 표 확인 |
| 선택 | wttr.in 어댑터, 실제 관측값 비교 | 필요해지면 |

---

## 9. 결정 사항

정한 것 (2026-10-23):
- 수집: 도시별 현지 22시, cron 30분 간격 (`./run.sh install`)
- city_id: UUID
- accuracy: 날짜 × n일전(1~14)마다 d0와 비교한 한 줄, 월별·연도별로 같은 n일전끼리 평균 (4.3, 5.2)
- weather_match: 카테고리 기준 (정도 차이는 weather_severity)
- 수집 실패: 로그 파일 + error_log 테이블, 알림은 웹에서 (미확인만 표시)
- 테스트: `python3 -m unittest`
- 설치: `python3 -m accu_weather setup` (curses TUI, 언어 → 소개 → 자동 실행 안내 → 도시 추가 → 설치)
- 백업: 저장 직후 `.backup` 사본 → rsync(다른 드라이브) 또는 클라우드, 세부는 미정
- 웹: 추후 Flask (보류)

남은 것 (기본값으로 진행해도 됨):

1. **확정 시각**: 22시 (기본) — 다른 시각을 원하면 config에서 변경
2. **하루 통합 날씨 규칙**: "가중치가 가장 큰 날씨" (기본, 구현됨) vs "가장 많이 나온 날씨"
3. **첫 등록 도시**: 오사카(기존 테스트 파일 좌표 34.70, 135.50) 외에 처음부터 넣을 도시
