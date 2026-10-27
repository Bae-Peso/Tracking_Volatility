# 날씨 예보 변동성 추적기 — 계획서

작성일: 2026-10-22 / 수정: 2026-10-27
- v2: 데이터 소스·DB 구조·정확도 기준 변경
- v3: 도시별 현지 22시 수집(cron 30분 간격), city_id UUID
- v4: 정확도를 "날짜 × n일전" 한 줄씩(d0와 비교)으로 바꾸고 월별·연도별로 n일전끼리 평균, error_log 추가
- v5: 설치 TUI(`setup`, 도시 추가·등록 취소), 백업 방향(rsync / 클라우드), 조회 단위(일별 / 주·월·연 평균)
- v6: Docker 이전 (수집 컨테이너가 `serve`로 30분마다 직접 실행, crontab 불필요)
- v7: 웹 조회 (Flask, 달력 주·월·연 + 일간 모달 + 그래프, 읽기 전용) — compose에 web·nginx 추가
- v8: 웹 다국어(i18n: 한·영·일), 그래프 점 단위 직접 선택(3시간 ~ 1달), 연간 달력 배치 자동 선택
- v9: 슬롯을 3시간 → 1시간으로 (그래프 점 단위 1시간 추가, 시간 단위 묶기는 서버에서). 기존 3시간 데이터는 리셋
- v10: 날씨 가중치를 (종류, 강도) 좌표의 넓이 → 코드별 이동·안전 영향 0~1로 (여러 도시 자료로 정함, 5.1), 체감온도 항목 추가, 점수 다섯 항목 0.2씩
- v11: 날씨·강수확률은 하루 대표값 차이에 3시간 묶음끼리의 차이를 반반 섞음 (대표값이 같으면 지속 시간·시각이 바뀌어도 0이던 문제, 5.1), 강수량은 로그 → 제곱근 척도

버전 : 0.6 (1~4단계 + recompute + 설치 TUI + Docker + 웹 조회 + 다국어)

---

## 1. 목표

- 사용자가 등록한 도시들의 **15일 예보(오늘 포함 2주)를 매일 각 도시 현지 시각 22시에 수집**한다 (22:30~23:30은 실패 대비 재시도).
- 같은 날짜·시간대에 대해 "14일 전, 13일 전 … 당일"에 각각 뭐라고 예보했는지 쌓는다.
- 정확도는 실측과의 비교가 아니라 **예보가 얼마나 자주·크게 바뀌었는지(변동성)** 로 본다.
  → "n일 전 예보가 다음 날 바뀔 확률" 정도를 1년간 모아서 보는 것이 목적. 엄밀한 정밀도는 필요 없음.
- NAS PC(일반 리눅스)에서 Docker 컨테이너 + Python + SQLite로 무인 가동한다 (7.6). Docker 없이 cron + bash로도 돌릴 수 있다.
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
| 시간 단위 | 3시간 (00~21시, 8개) | 1시간 그대로 사용 (00~23시, 24개) |
| 날씨 / 최고·최저 기온 / 바람 / 가시거리 / 강수량 / 강수확률 | 모두 있음 | 모두 있음 (확인함) |
| 도시 검색 | 이름으로 조회 가능 | 전용 지오코딩 API (**영어 이름으로 통일**, `language=en`) |
| 키 / 비용 | 없음 | 없음 (비상업 무료, 하루 1만 회 제한 → 충분) |
| 안정성 | 개인 운영 서비스라 가끔 느리거나 막힘 | API 전용 서비스 |

Open-Meteo의 1시간 값 중 먼 날짜는 전구 모델(3·6시간 간격)을 1시간으로 보간한 값이라,
lead_days가 클수록 1시간 슬롯끼리의 차이는 실제 해상도보다 촘촘해 보인다. 하루 통합 값 비교에는 영향이 적다.
저장량은 도시당 1년 약 32MB (3시간 슬롯이면 약 12MB, 2026-10-23 시뮬레이션).

**결정:** Open-Meteo를 기본으로 쓴다. 수집 코드는 소스별 어댑터로 나눠서,
원하면 wttr.in도 같은 테이블에 `source='wttr'`로 함께 넣을 수 있게 한다. 이 경우 lead는 0~2일만 채워진다.
나중에 "어느 서비스 예보가 더 오락가락하나" 비교도 가능하다.

### 사용 API

```
# 예보 (도시 여러 개를 한 번에 요청 가능: latitude=34.7,35.68&longitude=135.5,139.76)
https://api.open-meteo.com/v1/forecast
  ?latitude={lat}&longitude={lon}
  &hourly=weather_code,temperature_2m,apparent_temperature,wind_speed_10m,visibility,precipitation,precipitation_probability
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
  2) 1시간 값 → 1시간 슬롯(00,01,…,23) 행으로 (SLOT_HOURS=1. 3으로 바꾸면 3시간씩 묶음)
  3) 1시간 슬롯 24개를 하루 통합 행(slot='day')으로 계산
  4) weather 테이블에 저장 (도시당 슬롯 360행 + 하루 통합 15행)
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
| 날씨 | 24개 슬롯 중 `weather_weight.json` 가중치가 가장 큰 코드 (그래프에서 여러 시간을 묶을 때와 같은 규칙) |
| 최고 기온 / 최저 기온 | 슬롯 최고의 최대 / 슬롯 최저의 최소 |
| 최고 / 최저 체감온도 | 기온과 같음 |
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
여기에 1시간 슬롯과 관리용 칼럼을 추가했습니다.

```sql
CREATE TABLE weather (
  target_date  TEXT    NOT NULL,      -- 날짜 '2026-10-24'
  slot         TEXT    NOT NULL,      -- '00','01',…,'23' 또는 'day'(하루 통합)
  city_id      TEXT    NOT NULL REFERENCES city(city_id),  -- 도시 (uuid)
  lead_days    INTEGER NOT NULL,      -- n일전 예보 (0~14)
  weather      INTEGER,               -- 날씨 카테고리 (아래 표)
  weather_code INTEGER,               -- 소스 원본 코드 (재분류용)
  temp_max     REAL,                  -- 최고 기온 ℃
  temp_min     REAL,                  -- 최저 기온 ℃
  feel_max     REAL,                  -- 최고 체감온도 ℃ (Open-Meteo apparent_temperature: 습도·바람·햇볕 반영)
  feel_min     REAL,                  -- 최저 체감온도 ℃
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

-- 10/24 12시 슬롯을 모든 도시에서 비교
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

숫자가 클수록 "나쁜" 날씨다. 대표 날씨는 카테고리 최댓값이 아니라 `weather_weight.json` 가중치로 고른다 (3장 하루 통합 규칙).
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
  weather_diff     REAL,                  -- 대표 날씨 가중치 차이 + 시간대별 차이, 0~1 (5.1)
  temp_max_diff    REAL,                  -- n일전 − d0 ℃
  temp_min_diff    REAL,
  feel_max_diff    REAL,                  -- 체감온도 n일전 − d0 ℃
  feel_min_diff    REAL,
  precip_prob_diff INTEGER,               -- n일전 − d0 %p (하루 최대)
  precip_prob_hourly_diff REAL,           -- 같은 시각 묶음끼리 |n일전 − d0| %p의 평균 (5.1)
  precip_sqrt_diff REAL,                  -- √(n일전 mm) − √(d0 mm)
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

5개 항목을 각각 0(d0와 같음)~1(기준값 이상 차이)로 만든 뒤 **0.2씩 같은 가중치**로 합친다.
각 항목은 사람이 받는 영향이 서로 겹치지 않게 나눴다: 기온(더위·추위), 체감온도(습도·바람·햇볕), 강수(젖음), 날씨(이동·안전).

- **기온**: 최고·최저 기온 차이의 평균. 0℃ 차이를 best, 5℃ 이상 차이를 worst로 판단함
- **체감온도**: 기온과 같은 방식 (같은 5℃ 기준). 기온이 같아도 습도·바람·햇볕 예보가 바뀌면 체감은 달라진다.
  여름 더위는 생명과 관련되고, 겨울도 바람으로 체감이 크게 달라지므로 기온과 따로 본다.
  Open-Meteo `apparent_temperature`는 습도(28℃ 이상에서 습도 80%↑면 기온보다 평균 +6℃), 바람(영하에서 −4 ~ −7℃),
  햇볕(일사 600W/m² 이상에서 약 +1.5℃)을 반영한다 (2026-10 여러 도시 자료로 확인).
  구름 양은 햇볕을 잘 대신하지 못해(낮 일사량이 구름 30% 미만 621 / 80% 이상 603 W/m²) 따로 받지 않는다.
- **날씨**: 예보와 당일의 날씨 코드가 **이동·안전**에 주는 영향이 얼마나 다른가.
  코드마다 가중치 0~1을 `weather_weight.json`에 두고, 대표 날씨끼리의 `|가중치(n일전) − 가중치(d0)|`와
  시간대별 차이(아래 "시간대별 비교")를 반반 섞어 `weather_diff`로 둔다.
  - 왜 이동·안전만 보나: Open-Meteo의 이슬비·비 코드는 사실상 강수량 구간이고(51 → 53 → 55 → 61 → 63 평균 0.18 → 0.66 → 1.12 → 1.37 → 4.22 mm/h),
    비 ↔ 눈은 거의 기온이 정한다. 강수량·기온은 이미 다른 항목이라, 날씨 항목은 그 둘로는 안 잡히는 것(안개의 시야, 눈길, 빙판, 돌풍, 뇌우)만 본다.
  - 정하는 방법: 여러 기후대 24개 도시의 28일치 1시간 예보로 코드별 위험 요소를 평균 냈다 (`tools/weight_study.py`).
    요소는 시야(5km → 0, 1km 이하 → 1), 눈(시간당 1cm 이상 → 1), 빙판(1℃ 이하에서 강수 → 0.5), 돌풍(30 → 0, 70km/h 이상 → 1).
    `1 − Π(1 − 요소)`로 합쳐 하나만 커도 커지게 하고, 맑음에도 부는 바람만큼 빼서 맑음 = 0으로 맞췄다.
  - 판단으로 고친 것: 표본이 없거나 아주 적은 코드(48 서리 안개, 56·57 어는 이슬비, 66·67 어는 비, 75 강한 눈, 77 싸라기눈, 82 강한 소나기, 86, 96·97·99),
    안개(자료 0.99 → 0.8: 시야는 최악이지만 길 자체가 위험해지진 않음), 뇌우(자료 0.29 → 0.75: 번개·정전 위험은 자료에 없음),
    강도 순서(강한 비 0.34 → 0.45). 싸라기눈은 약한 눈보다 낮게(0.45), 어는 이슬비는 어는 비보다 0.2 낮게(0.5 / 0.65).
  - 1 = 99 강한 우박을 동반한 뇌우. 맑음 ↔ 구름은 0 ↔ 0.05라 거의 감점이 없다.
  - 자료는 10월 말 한 달이라 겨울·장마철 날씨가 적다. 데이터가 쌓이면 같은 스크립트로 다시 계산해 본다.
  - 처음에는 (종류 x, 강도 y) 좌표의 넓이 x·y를 썼는데, 종류가 달라도 넓이가 같으면 차이가 0이 되고(강한 이슬비 ↔ 비, 안개 ↔ 약한 이슬비)
    x 순서가 "얼마나 다른 날씨인가"를 나타내지 못해 바꿨다.
  - `weather_match`는 카테고리만 본다 (약한 비 ↔ 강한 비도 "비"로 같음). 정도의 차이는 `weather_diff`가 반영한다.
- **강우량**: **제곱근 척도**(`√mm`)로 차이를 잰다. 기본값은 0mm ↔ 10mm 차이(`√10` ≈ 3.16)를 worst로 둔다.
  0 → 1mm(우산이 필요해짐, 0.32)는 10 → 11mm(어차피 비, 0.15)보다 크게 잡히고, 많은 비 쪽 차이도 작아지지 않는다(10 → 20mm 0.41, 30 → 50mm 0.50).
  - 처음에는 로그 척도(`log1p(mm)`, worst `log1p(10)`)를 썼다. 비율만 보다 보니 10 → 20mm가 0.27, 30 → 50mm가 0.21로
    0 → 1mm(0.29)보다도 작아, 10mm와 20mm처럼 실제로는 꽤 큰 차이를 작게 봐서 바꿨다.
- **강수확률**: 0~100(%) 고정 범위이므로 차이를 100으로 나눠 그대로 쓴다. 하루 최대 차이와 시간대별 차이를 반반 섞는다.
- **시간대별 비교 (날씨·강수확률)**: 하루 대표값(가장 나쁜 날씨, 최대 확률)만 비교하면 "강한 비 2시간 ↔ 20시간",
  "오전 비 ↔ 저녁 비"처럼 대표값이 같은 날은 차이가 0이 된다. 그래서 1시간 슬롯을 3시간씩 8묶음(묶음마다 최댓값)으로 나눠
  같은 묶음끼리 `|n일전 − d0|`의 평균을 내고, 대표값 차이와 반반(`peak_share = 0.5`) 섞는다.
  - 하루 평균끼리 비교하지 않은 이유: 오전 비 ↔ 저녁 비처럼 시각만 옮겨 가면 평균이 같아 다시 0이 된다.
  - 시간대별 차만 쓰지 않은 이유: 1시간짜리 뇌우를 놓쳐도 1/8로 묽어진다. 대표값 쪽이 "그날 한 번이라도 위험했나"를 맡는다.
  - 3시간 묶음인 이유: 며칠 전 예보가 비 오는 시각을 1시간 단위로 맞히긴 어렵다. 1~2시간 어긋난 건 같다고 본다 (`block_hours`).
  - 둘 다 있는 묶음이 없으면(슬롯이 없으면) 대표값 차이만 쓴다.

```python
def score(row):   # accu_weather/accuracy.py
    temp = min((abs(temp_max_diff) + abs(temp_min_diff)) / 2 / 5.0, 1.0)
    feel = min((abs(feel_max_diff) + abs(feel_min_diff)) / 2 / 5.0, 1.0)
    prob = min(mix(abs(precip_prob_diff), precip_prob_hourly_diff) / 100.0, 1.0)   # mix = 0.5 × 대표 + 0.5 × 시간대별
    rain = min(abs(precip_sqrt_diff) / math.sqrt(10.0), 1.0)
    return round(100 * (1 - 0.2 * (temp + feel + prob + rain + weather_diff)), 1)    # weather_diff도 mix한 값
```

가중치(0.2 × 5), 기준값(5℃, 10mm), 시간대별 비교(`block_hours`, `peak_share`)는 `config.toml`의 `[accuracy]`, 날씨 가중치는 `weather_weight.json`에서 바꾼다.
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
- 출력은 웹 조회 화면에서 한다 (7.5). CLI 조회 명령은 두지 않는다. SQL로 직접 볼 때는 `sqlite3 -readonly` 나 DB 뷰어.

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
├─ run.sh                 # cron 진입점 (Docker 없이 돌릴 때)
├─ Dockerfile             # 수집기 이미지 (ENTRYPOINT python3 -m accu_weather, CMD serve)
├─ compose.yaml           # collector 서비스 (웹은 6단계에서 추가)
├─ cities.txt             # city export/import 파일
├─ weather_code.json      # WMO 코드 → 카테고리, 이름
├─ weather_weight.json    # WMO 코드 → 가중치 0~1 (이동·안전 영향, 5.1)
├─ tools/weight_study.py  # 가중치를 정할 때 쓴 분석 (여러 도시 자료 → 코드별 영향)
├─ accu_weather/
│   ├─ __main__.py        # setup / collect / serve / recompute / city
│   ├─ scheduler.py       # serve: 매 :00/:30에 collect (Docker용, cron 대신)
│   ├─ setup_tui.py       # 설치 TUI (curses)
│   ├─ setup_text.py      # 설치 TUI 문구 (ko / en / ja)
│   ├─ config.py          # config.toml 읽기
│   ├─ codes.py           # 카테고리, 가중치, 대표 날씨
│   ├─ collect.py         # 현지 22시가 지난 도시 골라서 수집
│   ├─ sources/
│   │   ├─ openmeteo.py   # 요청 + 1시간 슬롯 변환 + 도시 검색
│   │   └─ wttr.py        # (선택) wttr.in 어댑터
│   ├─ db.py              # 스키마, 도시, upsert
│   ├─ daily.py           # 하루 통합
│   └─ accuracy.py        # n일전 vs d0 정확도
├─ web/                   # 웹 조회 (Flask, 7.5)
│   ├─ app.py             # /, /api/* (읽기 전용)
│   ├─ queries.py         # 달력·일간·그래프 데이터 (표준 라이브러리만, 테스트 가능)
│   ├─ templates/index.html, static/app.js, static/style.css
│   ├─ static/vendor/     # Chart.js 4.5.1 (MIT)
│   ├─ Dockerfile, nginx.conf, requirements.txt
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
*/30 * * * *  /.../Tracking_Volatility/accu_weather/run.sh
```

- 수집 줄은 `./run.sh install`로 등록, `./run.sh uninstall`로 제거한다 (run.sh 줄만 교체, 다른 crontab 줄은 유지).
- 수집 cron은 서버 시간대와 상관없이 30분마다 돈다. 어느 도시를 받을지는 스크립트가 `city.timezone` 기준으로 판단한다.
  → 도시를 추가·삭제해도 crontab은 그대로, 서머타임도 `zoneinfo`가 처리.
- 날짜·슬롯·lead_days, "오늘 이미 받았나" 판단 모두 각 도시의 `city.timezone` 기준.
- 매 실행 결과(저장 행 수, 실패)는 `logs/YYYY-MM.log`에 기록한다. 실패는 `error_log` 테이블에도 남긴다 (4.4).
- 수집 실패 알림(메일·메신저)은 두지 않는다. 웹 조회를 만들면 `error_log`의 미확인 항목을 알림으로 보여준다.

### 7.4 백업 (보류)

백업 위치(다른 드라이브, NAS 공유 폴더, 클라우드)는 사용자마다 달라서 기능으로 넣지 않고 보류한다. 아래는 정해 둔 방향.

- **시점**: 수집이 실제로 저장한 실행 뒤에 한다 (도시마다 현지 22시가 달라서 고정 시각 대신 "저장 직후").
  run.sh에서 collect가 저장한 경우에만 이어서 백업을 돌린다.
- **방법**: 먼저 `sqlite3 data/weather.sqlite3 ".backup ..."`으로 일관된 사본을 만들고 (쓰는 중인 파일을 그대로 복사하지 않음), 그 사본을
  - 다른 드라이브·NAS 공유 폴더로 `rsync`, 또는
  - 가능하면 클라우드 저장소로 업로드 (예: `rclone`).
- 정할 것: 백업 위치, 보관 개수(예: 최근 n개만), 클라우드 사용 여부.

### 7.5 웹 조회

읽기 전용, 로그인 없음. `http://<이 PC 주소>:8080` (포트는 `.env`의 `WEB_PORT`).

**구성**: nginx(HTTP 포트) → web(Flask + gunicorn :8000) → `data/weather.sqlite3`를 `mode=ro`로 연다.
"표준 라이브러리만" 원칙은 수집 쪽(`accu_weather/`)에만 적용하고, Flask는 `web/`에만 쓴다.
그래프는 Chart.js(4.5.1)를 `web/static/vendor/`에 넣어 CDN 없이 동작한다.

| 화면 | 내용 |
|---|---|
| 상단 | 표시 모드 [달력 \| 그래프], 수집 실패 알림 (아래) |
| 달력 · 왼쪽 | 도시 목록 (좁은 화면에서는 위쪽 선택 상자) |
| 달력 · 주 | 7행(일~토) × 15열(**당일** → 하루 전 → … → 14일 전), 오른쪽 위 드롭다운의 항목 값 + 색. 당일 열은 실제 예보 값. 좁은 화면에서는 15행 × 7열로 뒤집음 |
| 달력 · 월 | 보통 달력 모양으로 화면을 채움. 칸마다 날짜, 당일 날씨·최고/최저기온, 아래 14칸 띠 (왼쪽 하루 전 → 오른쪽 14일 전), 색 = 변동 정도 |
| 달력 · 연 | 화면을 채움. 배치는 화면 비율에 따라 4×3 / 3×4 / 6×2 / 2×6 / 12×1 중 날짜 칸이 가장 큰 것 (어떤 배치로도 칸이 12px 미만이면 칸 크기를 고정하고 가로·세로 스크롤). 날짜마다 14개 변동 정도의 **중앙값** → 그 해 다른 날짜와의 **순위**로 색 |
| 일간 모달 | 날짜를 누르면. 14일 전 → 당일 그래프 (당일 = 0, 값 = n일 전 − 당일), [그래프 \| 표] 전환. 날씨는 값 대신 변동성(0~1) |
| 그래프 | **1·2·4·8·16 분할**, 분할마다 왼쪽 위에서 도시·항목 선택. n일 전(당일~14일 전)별 선, 오른쪽 버튼으로 켜고 끔 (모든 분할 공통). 보이는 기간도 모든 분할이 함께 움직이고, **한 그래프에 커서를 올리면 다른 분할에도 같은 시각에 세로선·툴팁**. [그래프 \| 표] 전환 |
| 그래프 항목 | 최고기온, 최저기온, **최고·최저기온**(한 그래프에 둘 다: 진한 선 최고, 옅은 선 최저), 최고·최저 체감온도(따로, 함께), 강수확률, 강수량, 바람, 가시거리, 날씨 변동성(같은 시각 당일 예보와의 날씨 가중치 차이. 당일 선 없음, d0가 생기는 수집 2일째부터) |
| 그래프 조작 | **휠**: 확대·축소 (마우스 위치 기준) · **Shift+휠 / 가로 휠 / 끌기**: 앞뒤 이동 · 기간 버튼 (지난 7일 ~ 2년). 최대 범위 2년 전 ~ 앞으로 14일 |
| 그래프 점 단위 | 사용자가 고름 (주식 차트의 봉처럼): **1시간 · 3시간 · 6시간 · 12시간 · 1일 · 3일 · 1주(월요일 시작) · 1달**. 자동으로 바뀌지 않는다. 눈금은 점과 같은 자리(3일·1주·1달은 구간 시작)에 |
| 묶는 규칙 | 3·6·12시간·1일: 일간 보기의 하루 통합과 같은 규칙 — 최고기온 **최대**, 최저기온 **최소**, 강수량 합계, 강수확률·바람 최대, 가시거리 최소, 날씨는 가장 나쁜 날씨 (1일은 저장된 하루 통합 행 그대로). 3일·1주·1달: 하루 값의 **평균**(= 평균 최고·최저기온), 강수량은 합계 |
| 단위별 최대 기간 | 1시간 20일, 3시간 60일, 6시간 120일, 12시간 240일, 1일 이상 2년. 넘는 기간 버튼은 비활성, 휠 축소도 거기서 멈추고 "단위를 키우세요" 안내 (1시간으로 2년이면 그래프 하나에 26만 점이라 느려짐) |
| 그래프 데이터 | 서버는 1시간 슬롯을 1·3·6·12시간으로 묶은 값(`step=slot&hours=n`)과 하루 통합 값(`step=day`, 일간 보기와 같은 행)을 준다 (12시간으로 240일을 볼 때 1시간 원본을 다 보내지 않도록 서버에서 묶음). 3일·1주·1달은 하루 값을 화면에서 묶는다. 하루 값은 도시·항목마다 2년치를 한 번에(수백 KB), 시간 단위 값은 보이는 기간 앞뒤로만 받아 두고 움직이면 더 받음 |

- **달력 항목**: 종합 점수, 날씨 변동성, 최고·최저기온 차이, 강수확률 차이, 강수량 차이.
- **색 (변동 정도 0~1)**: 초록 → 노랑 → 빨강. 항목별 기준은 정확도 점수와 같다
  (기온 |차이|/5℃, 강수확률 |차이|/100, 강수량 제곱근 차이/√10mm, 날씨 = 변동성, 점수 = (100 − 점수)/50). 1 이상은 1.
  색만으로 읽지 않도록 범례, 마우스를 올리면 값, 주간 표의 숫자가 함께 있다.
- **선 색**: 당일(기준)은 무채색 굵은 선(글자색), 하루 전 ~ 14일 전은 선명한 7색을 두 날씩 (1·2일 전, 3·4일 전 … 13·14일 전, 홀수 실선·짝수 점선).
  범주 팔레트에서 빨강을 뺀 청록 → 파랑 → 초록 → 분홍 → 노랑 → 보라 → 주황 (이웃 색끼리 색각이상 ΔE 13 이상, 라이트·다크 모두 검증).
  처음에는 viridis 순서형 색을 썼는데, 이웃한 날의 색이 비슷해 1·3·5일 전처럼 같은 실선끼리 구분이 안 돼 바꿨다.
  당일을 주황으로 두면 빨강·노랑·분홍과 구분이 안 돼(일반 시각 ΔE 15 미만) 무채색으로 바꿨다.
  한 가지 색의 밝기만 쓰던 처음 방식보다 색상 차이가 커서 몇 칸만 떨어져도 잘 구분된다. 바로 옆 n일 전끼리는 어떤 색 체계로도 구분이 어려우므로
  **짝수 n일 전은 점선**으로 한 번 더 구분하고, 버튼 이름·툴팁·버튼에 올리면 그 선만 진하게 보이기·분할로 보완한다.
- **주 시작**: 달력은 일요일 시작 (5.2의 주별 평균 SQL은 ISO 주, 월요일 시작).
- **수집 실패 알림**: `error_log`의 미확인(`read_at` 없음) 항목을 상단에 ⚠ 배너로. 웹은 읽기 전용이라 DB의 `read_at`은 바꾸지 않고,
  "확인"한 마지막 번호를 **브라우저에 저장**해 그 뒤 것만 보여준다 (DB 기록은 그대로, 다른 브라우저에서는 다시 보임).
- **DB 동시 접근**: 쓰기는 하루 몇 번, 몇 밀리초라서 WAL 없이 기본 모드로 둔다. 웹은 읽기 전용 + 잠금 대기 5초.
  (WAL은 읽는 쪽도 `-shm` 파일을 써야 해서 `:ro` 볼륨과 맞지 않음)
- **공개 범위**: 미정. 지금은 집 안 기준(인증 없음). 외부에 열 때 `web/nginx.conf`에 HTTPS와 인증을 붙인다.
- 화면 높이: 넓은 화면에서는 달력·그래프가 화면 높이를 꽉 채운다 (16분할도 한 화면). 좁은 화면(760px 이하)은 위아래 스크롤, 그래프는 손가락으로 끌어 이동.
- **다국어 (i18n)**: 상단 언어 선택 (한국어 / English / 日本語, 처음에는 브라우저 언어, 고르면 브라우저에 저장).
  - 화면 문구: `web/static/i18n/<언어>.json` (키 → 문구, `{n}` 같은 자리표시자). 언어 목록: `web/static/i18n/languages.json`.
  - 날씨 이름: `weather_code.json`의 언어별 이름 (서버가 `/api/meta`의 `weather_names`로 넘김).
  - 서버는 문구를 보내지 않는다: 날씨는 코드, 오류는 코드(`err.*`)로 보내고 화면이 번역한다.
  - **언어 추가**: ① `en.json`을 복사해 `<코드>.json`으로 번역 ② `languages.json`에 한 줄 ③ `weather_code.json`에 그 언어 이름.
    새 파일에 빠진 키는 영어로 보이고, `python3 -m unittest`가 빠진 키·틀린 자리표시자·빠진 날씨 이름을 잡아낸다.
  - 설치 TUI의 언어(`accu_weather/setup_text.py`)와는 따로다.
- 개발: `pip install -r web/requirements.txt` 후 `flask --app web.app run`.

### 7.6 Docker

일반 리눅스 PC에 Docker Engine + compose 플러그인만 있으면 된다 (NAS 전용 기능 불필요).

| 항목 | 방식 |
|---|---|
| 이미지 | `python:3.13-slim` + `tzdata`(pip, zoneinfo용). 코드·JSON·config를 담고 `ENTRYPOINT python3 -m accu_weather`, 기본 `CMD serve` |
| 스케줄 | 컨테이너 안에 cron 없음. `serve`가 시작 직후 한 번, 그 뒤 매 :00/:30에 collect. 받을 도시만 받는 판단은 그대로 |
| 재시작 | `restart: unless-stopped` → 컴퓨터를 다시 켜도 자동 재개 |
| 데이터 | `./data`를 그대로 연결 (기존 DB 그대로 사용, 옮길 필요 없음). config.toml·JSON은 읽기 전용으로 연결 → 고친 뒤 재시작 |
| 권한 | `user: UID:GID`, 기본 1000 (대부분 배포판의 첫 계정). 다르면 `.env`에 `UID=$(id -u)`, `GID=$(id -g)` (이 PC는 1003). `data/`는 미리 `mkdir` (없으면 Docker가 root 소유로 만듦) |
| 로그 | 표준 출력 → `docker compose logs collector` (10MB × 3개로 회전). 실패는 error_log에도 |
| 종료 | `docker stop`의 SIGTERM을 받으면 바로 끝냄 (PID 1은 핸들러가 없으면 무시하므로 직접 처리) |
| 설치 TUI | `docker compose run --rm collector setup`. 컨테이너 안에서는 crontab 대신 수집 컨테이너를 안내 (`ACCU_WEATHER_DOCKER=1`) |

```bash
docker compose up -d --build                 # 수집 시작
docker compose logs -f collector             # 로그
docker compose run --rm collector setup      # 설치 TUI (도시 추가·등록 취소)
docker compose run --rm collector city list  # 그 밖의 명령 (collect --force, recompute …)
docker compose run --rm collector city export data/cities.txt   # 컨테이너 안 /app 은 사라지므로 data/ 에
```

**호스트 cron → Docker 이전 순서**

1. Docker Engine + compose 플러그인 설치 (https://docs.docker.com/engine/install/).
   sudo 없이 쓰려면 `sudo usermod -aG docker $USER` 후 다시 로그인 (선택, docker 그룹은 사실상 root 권한)
2. `mkdir -p data`, UID/GID가 1000이 아니면 `printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env`
3. `./run.sh uninstall` — 호스트 crontab의 수집 줄 제거 (둘이 같이 돌지 않게)
4. `docker compose up -d --build`
5. `docker compose logs collector`에 `serve: collect every 30 min`이 보이면 끝. 다음 현지 22시에 `saved …` 줄이 찍힌다.

되돌리기: `docker compose down` 후 `./run.sh install`. 데이터는 같은 `data/`라서 그대로 이어진다.

## 8. 단계별 진행

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 1 | ✅ 스키마 + `city add/list` + Open-Meteo 수집 + 3시간 슬롯 upsert | 수동 실행으로 weather에 15일치가 들어감 |
| 2 | ✅ run.sh + crontab 등록 (`./run.sh install`, 30분 간격, 도시별 현지 22시 판단) | **가능한 빨리 가동** (강수확률·가시거리는 과거 데이터로 소급 불가) |
| 3 | ✅ 하루 통합 | 22시 실행 후 `slot='day'` 행 생성 |
| 4 | 정확도 (n일전 vs d0) + error_log + 테스트 | ✅ 구현. 가동 다음 날부터 1일전 행이 생기고, 15일 뒤 1~14일전이 다 참 |
| 5 | recompute ✅ + 설치 TUI ✅ + 백업 (7.4, 보류) | 백업 위치는 사용자마다 달라 보류 |
| 5.5 | Docker 이전 (7.6) | `docker compose up -d` 후 현지 22시 수집이 logs에 찍힘 |
| 6 | ✅ 웹 조회 (nginx + Flask, 7.5) | 브라우저에서 달력·일간·그래프 확인 |
| 선택 | wttr.in 어댑터, 실제 관측값 비교 | 필요해지면 |

---

## 9. 결정 사항

정한 것 (2026-10-23):
- 수집: 도시별 현지 22시, cron 30분 간격 (`./run.sh install`)
- city_id: UUID
- accuracy: 날짜 × n일전(1~14)마다 d0와 비교한 한 줄, 월별·연도별로 같은 n일전끼리 평균 (4.3, 5.2)
- weather_match: 카테고리 기준 (정도 차이는 weather_diff)
- 점수 (2026-10-24): 기온·체감온도·강수확률·강수량·날씨 0.2씩. 날씨 가중치는 이동·안전 영향 0~1, 차이는 |A − B| (5.1)
- 수집 실패: 로그 파일 + error_log 테이블, 알림은 웹에서 (미확인만 표시)
- 테스트: `python3 -m unittest`
- 설치: `python3 -m accu_weather setup` (curses TUI, 언어 → 소개 → 자동 실행 안내 → 도시 추가 → 설치)
- 백업: 보류 (위치가 사용자마다 다름). 방향은 저장 직후 `.backup` 사본 → rsync(다른 드라이브) 또는 클라우드
- 데이터 출처 표기: Open-Meteo는 CC BY 4.0 → 웹 상단과 README에 "Weather data by Open-Meteo.com" 링크
- 실행 환경: 일반 리눅스 PC + Docker. 수집 컨테이너가 직접 30분마다 실행 (7.6)
- 작업 순서: Docker 먼저, 그다음 웹(compose에 서비스 추가)
- 웹: Flask, 읽기 전용, 로그인 없음. 공개 범위는 미정 → 우선 집 안 기준, 외부 공개 시 nginx에 HTTPS·인증
- 수집 실패 알림의 "확인"은 브라우저에 저장 (웹이 DB에 쓰지 않으므로)

남은 것 (기본값으로 진행해도 됨):

1. **확정 시각**: 22시 (기본) — 다른 시각을 원하면 config에서 변경
2. **하루 통합 날씨 규칙**: "가중치가 가장 큰 날씨" (기본, 구현됨) vs "가장 많이 나온 날씨"
3. **첫 등록 도시**: 오사카(기존 테스트 파일 좌표 34.70, 135.50) 외에 처음부터 넣을 도시
