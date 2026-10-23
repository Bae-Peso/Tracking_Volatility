# 예보 변동성 추적기 (Tracking Volatility)

**한국어** | [English](README.en.md) | [日本語](README.ja.md)

> **"14일 전 일기예보는 얼마나 믿을 만할까?"**
> 같은 날짜에 대한 예보가 14일 전부터 당일까지 어떻게 바뀌는지 매일 기록하고, 며칠 전 예보부터 믿을 만한지 비교하는 셀프 호스팅 도구.

등록한 도시들의 15일 예보를 매일 **도시 현지 시각 22시**에 [Open-Meteo](https://open-meteo.com/)에서 받아 SQLite에 쌓는다.
날짜마다 "n일 전(1~14) 예보가 당일 22시 예보와 얼마나 달랐나"를 점수로 남기고,
웹 화면에서 일별로 그대로 보거나 주별·월별·연도별로 같은 n일 전끼리 비교한다.

<!-- 스크린샷: 실데이터가 쌓이면 추가 (월간 달력, 일간 보기, 4분할 그래프) -->
<img width="2364" height="1393" alt="image" src="https://github.com/user-attachments/assets/10a2e63a-a5e6-46e0-85fd-e5164954eea7" />

**위 사진은 아직 데이터가 축적되기 이전 및 이전 버전의 사진으로 현재 버전과 보이는 구조에 차이가 있을 수 있습니다.**

## 주요 기능

- **수집**: 도시마다 현지 22시에 15일 예보(1시간 단위)를 받아 1시간 슬롯과 하루 통합 값으로 저장. 실패하면 다음 30분에 재시도하고 기록을 남김
- **정확도**: 날짜 × n일 전(1~14)마다 당일 예보와 비교한 차이(기온·강수확률·강수량·날씨)와 종합 점수
- **웹 조회** (읽기 전용)
  - 달력: 주(당일 + 14개 n일 전 값), 월(날짜마다 14칸 색 띠), 연(그 해 다른 날과 비교한 색)
  - 일간 보기: 14일 전 → 당일 예보가 당일과 얼마나 달랐나 (그래프 / 표)
  - 그래프: 1·2·4·8·16 분할, 분할 간 커서 동기화, 최고·최저기온 함께 보기, 점 단위 1시간 ~ 1달, 휠 확대·축소와 끌어서 이동 (최대 2년)
  - 한국어 / English / 日本語, 라이트·다크 모드, 휴대폰 화면
- **설치 TUI** (한·영·일): 도시 검색·추가·등록 취소, 자동 실행 등록
- **Docker Compose**로 수집기·웹·nginx를 한 번에 실행, 재부팅 후 자동 재시작

## 구성

```
                   매 :00 / :30, 현지 22시가 지난 도시만
  Open-Meteo API  ───────────────────────────────▶  collector (Python 표준 라이브러리)
                                                        │ 쓰기
  설치 TUI (curses) ── 도시 추가·취소 ──────────────────▶ │
                                                        ▼
                                              data/weather.sqlite3
                                                        │ 읽기 전용
                                                        ▼
  브라우저  ◀── nginx :8080 ◀── web (Flask + gunicorn, /api/* JSON)
```

| 영역 | 기술 |
|---|---|
| 수집·정확도 계산 | Python 3.11+ **표준 라이브러리만** (`urllib`, `sqlite3`, `zoneinfo`, `tomllib`, `curses`) |
| 저장 | SQLite (`city`, `weather`, `accuracy`, `error_log`) |
| 웹 | Flask + gunicorn, nginx, Chart.js 4.5 (저장소에 포함), 바닐라 JS, i18n JSON |
| 실행 | Docker Compose (collector · web · nginx) 또는 cron |
| 테스트 | `unittest` 70여 개 (네트워크 없이 1초 이내) |

## 설계하면서 고민한 점

자세한 기록과 변경 이유(v1 → v8)는 [PLAN.md](PLAN.md)에 있다.

- **정답 대신 "당일 22시 예보"를 기준으로** — 실측을 따로 모으지 않고 예보가 얼마나 흔들렸는지에 집중했다. 당일 밤 예보는 이미 지나간 시간대에 대해서는 사실상 실측에 가깝다.
- **도시마다 현지 22시에 수집** — 한 시각에 모든 도시를 받으면 도시마다 "당일 예보"의 의미가 달라진다 (서울 22시 = 뉴욕 오전 9시). 그래서 30분마다 깨어나 현지 22시가 지난 도시만 받는다. 서머타임은 `zoneinfo`가 처리한다.
- **정확도를 "날짜 × n일 전" 한 줄씩** — 처음에는 날짜마다 점수 하나(범위 기반)였지만, n일 전 정보가 사라지고 수집이 빠진 날은 범위가 좁아져 점수가 좋게 나오는 편향이 있었다. n일 전마다 따로 저장하니 "11월의 7일 전 예보 정확도" 같은 월별·연도별 평균이 자연스럽게 나온다.
- **날씨 변화의 크기** — WMO 날씨 코드 번호는 심각도 순서가 아니어서(예: 77 싸라기눈 > 75 강한 눈), 코드마다 (종류, 강도) 좌표를 두고 그 넓이를 가중치로 썼다. 맑음 → 구름은 작게, 맑음 → 뇌우는 크게 감점된다. 강수량은 0 → 1mm와 10 → 11mm의 체감 차이를 반영해 로그 척도로 비교한다.
- **집계 규칙** — 그래프를 3·6시간·하루로 묶을 때 최고기온은 최대, 최저기온은 최소, 강수량은 합계. 여러 날로 묶을 때는 하루 최고기온의 평균(평균 최고기온)으로, 1시간 기온을 평균 내는 실수를 피했다.
- **`city_id`는 UUID** — 이름이나 좌표를 고쳐도 키가 바뀌지 않고, 도시 목록을 내보냈다 다른 DB에 불러와도 같은 도시로 이어진다.
- **쓰는 곳은 하나, 웹은 읽기 전용** — 쓰기는 수집기 하나만 해서 SQLite 동시성 문제를 단순하게 했다. 웹은 `mode=ro`로 열고, 읽기 쪽도 파일을 써야 하는 WAL 대신 기본 저널 모드 + 잠금 대기를 썼다.
- **수집기는 표준 라이브러리만** — 의존성 없이 어떤 리눅스에서도 돌도록 했다. Flask는 웹 쪽에만 쓴다.
- **서버는 문구 대신 코드를 보낸다** — 날씨는 WMO 코드, 오류는 오류 코드로 보내고 번역은 화면의 언어 파일이 한다. 언어 추가는 JSON 파일 하나로 끝나고, 빠진 키는 테스트가 잡아낸다.

## 빠른 시작 (Docker)

일반 리눅스 PC에 Docker Engine과 compose 플러그인이 있으면 된다 (설치: https://docs.docker.com/engine/install/).

```bash
mkdir -p data                                          # 먼저 만든다 (없으면 Docker가 root 소유로 만듦)
printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env  # UID/GID가 1000이면 생략 가능
docker compose run --rm collector setup                # 설치 TUI: 언어 → 소개 → 자동 실행 안내 → 도시 추가 → 설치
docker compose up -d --build                           # 수집 + 웹 시작 (재부팅 후 자동 재시작)
docker compose logs -f collector                       # "serve: collect every 30 min" 이 보이면 정상
```

웹 조회: `http://<이 PC 주소>:8080` (포트는 `.env`의 `WEB_PORT`). 읽기 전용이고 로그인은 없다.

<details>
<summary>Docker 설정 참고 (sudo 없이 쓰기, UID/GID, 호스트 cron에서 옮기기)</summary>

- sudo 없이 `docker`를 쓰려면 `sudo usermod -aG docker $USER` 후 다시 로그인한다.
  `docker` 그룹은 사실상 root 권한이므로 원하지 않으면 명령마다 `sudo`를 붙여도 된다
  ([linux-postinstall](https://docs.docker.com/engine/install/linux-postinstall/)).
- 컨테이너는 호스트 사용자와 같은 UID/GID로 `data/`에 쓴다. 기본값은 1000 (대부분 배포판에서 처음 만든 계정).
  셸의 `$UID`는 Docker로 전달되지 않고 `sudo`를 붙이면 환경변수가 초기화되므로 `.env` 파일로 넘긴다. `.env`는 git에 올리지 않는다.
- 그 밖의 명령은 `docker compose run --rm collector <명령>` (아래 "명령"의 `python3 -m accu_weather` 대신).
- 호스트 cron으로 돌리던 것을 옮길 때는 먼저 `./run.sh uninstall` (PLAN.md 7.6).

</details>

## Docker 없이

Python 3.11+와 cron, `flock`, `timeout`(리눅스 기본)이 있으면 된다.

```bash
python3 -m accu_weather setup      # 설치 TUI. 마지막 "설치"에서 도시 등록 + crontab에 30분 간격 등록
```

웹은 따로 띄운다: `pip install -r web/requirements.txt` 후 `flask --app web.app run`.

## 명령

```bash
python3 -m accu_weather setup                                       # 설치 TUI (다시 실행하면 등록 취소도 가능)
python3 -m accu_weather city add "Osaka"                            # 영어 이름으로 검색해서 추가
python3 -m accu_weather city add "Seoul" --lat 37.57 --lon 126.98   # 좌표로 추가 (시간대 자동)
python3 -m accu_weather city list [--all]
python3 -m accu_weather city disable <id> [--purge]                 # 수집 중단 / --purge: 데이터까지 삭제
python3 -m accu_weather city enable <id>
python3 -m accu_weather city export | import [path]                 # 도시 목록 ↔ cities.txt (city_id 포함)

python3 -m accu_weather collect [--force] [--city <id>]             # 수동 수집 (--force: 시각 무시)
python3 -m accu_weather serve                                       # 상주 실행: 매 :00/:30에 collect (Docker 기본 명령)
python3 -m accu_weather recompute [--city <id>]                     # 정확도 전체 재계산 (config 변경 후)

./run.sh install | uninstall                                        # crontab 등록 / 해제 (Docker 없이 돌릴 때)
```

`<id>`는 `city list`에 나오는 UUID 앞 8자리만 입력해도 된다.

## 웹 화면

| 모드 | 보기 |
|---|---|
| 달력 · 주 | 7일 × (당일 + 하루 전 ~ 14일 전), 고른 항목의 값과 색 |
| 달력 · 월 | 보통 달력. 칸마다 당일 날씨·기온과 14칸 띠 (하루 전 → 14일 전), 초록(변동 적음) → 빨강(많음) |
| 달력 · 연 | 화면 비율에 맞춰 4×3 / 3×4 / 6×2 …, 너무 작으면 스크롤. 날짜마다 변동 중앙값을 그 해 다른 날짜와 비교한 색 |
| 일간 (날짜 클릭) | 14일 전 → 당일 예보가 당일과 얼마나 달랐나, 그래프 / 표 |
| 그래프 | 분할마다 도시·항목 선택, n일 전별 예보 선. 점 단위 1시간 ~ 1달 (최고는 최대·최저는 최소, 여러 날이면 평균 최고·최저, 강수량은 합계) |

수집이 실패하면 상단에 ⚠ 알림이 뜬다 ("확인"은 그 브라우저에만 저장, DB 기록은 그대로).
언어 추가는 `web/static/i18n/`에 JSON 파일 하나 + `weather_code.json`에 날씨 이름 (PLAN.md 7.5).

## 프로젝트 구조

```
accu_weather/        수집기 (표준 라이브러리만): collect, scheduler(serve), accuracy, db, setup TUI
  sources/openmeteo.py   Open-Meteo 요청, 1시간 값 → 1시간 슬롯 행
web/                 웹 조회: app.py(Flask), queries.py(데이터), templates/, static/(app.js, i18n/, vendor/)
tests/               unittest (수집·정확도·스케줄러·TUI·웹·i18n 파일)
config.toml          수집 시각·기간, 정확도 가중치·기준값
weather_code.json    WMO 날씨 코드 → 카테고리, 이름(ko/en/ja)
weather_severity.json  WMO 날씨 코드 → (종류, 강도) 좌표
Dockerfile, web/Dockerfile, compose.yaml, run.sh
PLAN.md              설계 기록 (v1 ~ v8, 결정 사항)
```

## 테스트

```bash
python3 -m unittest        # 네트워크 없이 1초 이내 (Flask가 없으면 웹 엔드포인트 테스트는 건너뜀)
```

## 데이터 직접 보기

```bash
sqlite3 -readonly -box data/weather.sqlite3 \
  "SELECT target_date, lead_days, weather, temp_max, temp_min, precip_mm, precip_prob
   FROM weather JOIN city USING (city_id)
   WHERE city.name = 'Osaka' AND slot = 'day' ORDER BY target_date, lead_days DESC"
```

월별·주별 n일 전 정확도 쿼리는 [PLAN.md 5.2](PLAN.md) 참고.

## 데이터 출처

- 날씨 데이터: [Weather data by Open-Meteo.com](https://open-meteo.com/) ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). 웹 화면 상단에도 출처 링크를 표시한다.
- 그래프: [Chart.js](https://www.chartjs.org/) 4.5.1 (MIT, `web/static/vendor/`에 라이선스 포함)

## 라이선스

[MIT](LICENSE) © 2026 Bae_Peso
