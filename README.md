# Tracking_Volatility

등록한 도시들의 15일 예보를 매일 **도시 현지 시각 22시**에 [Open-Meteo](https://open-meteo.com/)에서 받아 SQLite에 저장하고,
날짜마다 "n일 전(1~14) 예보가 당일 22시 예보(d0)와 얼마나 같았나"를 쌓는다.
결과는 웹 화면에서 일별로 그대로 보거나, 주별·월별·연도별로 같은 n일전끼리 비교해 본다.
설계와 진행 상황은 [PLAN.md](PLAN.md) 참고.

## 요구 사항

- Python 3.11+ (표준 라이브러리만 사용, 설치 화면은 `curses`)
- Docker로 돌리면 위 둘 다 이미지 안에 있다. Docker 없이 돌리면 cron, `flock`, `timeout` (리눅스 기본)

## 시작하기 (Docker, 권장)

일반 리눅스 PC에 Docker Engine과 compose 플러그인이 있으면 된다.

### 1. Docker 준비 (처음 한 번)

- 설치: https://docs.docker.com/engine/install/
- (선택) sudo 없이 `docker`를 쓰려면 계정을 `docker` 그룹에 넣고 다시 로그인한다.
  `docker` 그룹은 사실상 root 권한이므로 원하지 않으면 아래 명령마다 `sudo`를 붙여도 된다.

  ```bash
  sudo usermod -aG docker $USER
  ```

  참고: https://docs.docker.com/engine/install/linux-postinstall/

### 2. 데이터 폴더와 사용자 ID (처음 한 번)

컨테이너는 호스트 사용자와 같은 UID/GID로 `data/`에 쓴다. 기본값은 **1000** (대부분 배포판에서 처음 만든 계정).

```bash
mkdir -p data      # 꼭 먼저 만든다. 없으면 Docker가 root 소유로 만들어 컨테이너가 쓰지 못한다
id -u; id -g       # 둘 다 1000이면 끝. 아니면 아래 한 줄
printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env
```

- `.env`는 PC마다 다르므로 git에 올리지 않는다 (`.gitignore`에 있음).
- 셸의 `$UID`는 Docker로 전달되지 않고, `sudo`를 붙이면 환경변수가 초기화되기 때문에 `.env` 파일로 넘긴다.

### 3. 설치와 실행

```bash
docker compose run --rm collector setup      # 설치 TUI: 언어 → 소개 → 자동 실행 안내 → 도시 추가 → 설치
docker compose up -d --build                 # 수집 + 웹 시작 (재부팅 후 자동 재시작)
docker compose logs -f collector             # "serve: collect every 30 min" 이 보이면 정상
```

웹 조회: `http://<이 PC 주소>:8080` (다른 포트를 쓰려면 `.env`에 `WEB_PORT=8090` 등). 읽기 전용이고 로그인은 없다.

컨테이너가 시작 직후와 매 :00/:30마다 현지 22시가 지났고 오늘 아직 받지 않은 도시만 받는다 (crontab 불필요).
데이터는 호스트의 `data/`에 그대로 쌓인다. 그 밖의 명령은 `docker compose run --rm collector <명령>` (아래 "명령"의 `python3 -m accu_weather` 대신).
호스트 cron으로 돌리던 것을 옮길 때는 먼저 `./run.sh uninstall` (PLAN.md 7.6).

## 시작하기 (Docker 없이)

```bash
python3 -m accu_weather setup
```

설치 화면(TUI)에서 언어 선택 → 소개 → 자동 실행 안내 → 도시 추가 → 설치 순서로 진행한다.
다시 실행하면 이미 등록된 도시를 등록 취소(수집 중단 / 완전 삭제)할 수도 있다.
마지막 "설치"에서 도시를 등록하고 crontab에 30분 간격 줄을 넣는다 (`./run.sh install`과 같음).

등록 후에는 30분마다 `run.sh`가 돌면서, 현지 22시가 지났고 오늘 아직 받지 않은 도시만 받는다.

## 명령

```bash
python3 -m accu_weather city add "Osaka"                            # 검색해서 추가
python3 -m accu_weather city add "Seoul" --lat 37.57 --lon 126.98   # 좌표로 추가 (시간대 자동)
python3 -m accu_weather city list [--all]
python3 -m accu_weather city disable <id> [--purge]                 # 수집 중단 / --purge: 데이터까지 삭제
python3 -m accu_weather city enable <id>
python3 -m accu_weather city export [path]                          # 도시 목록 → cities.txt
python3 -m accu_weather city import [path]                          # cities.txt → 도시 목록

python3 -m accu_weather collect [--force] [--city <id>]             # 수동 수집 (--force: 시각 무시)
python3 -m accu_weather serve                                       # 상주 실행: 매 :00/:30에 collect (Docker 기본 명령)
python3 -m accu_weather recompute [--city <id>]                     # 정확도 전체 재계산 (config 변경 후)

./run.sh install | uninstall                                        # crontab 등록 / 해제
```

`<id>`는 `city list`에 나오는 UUID 앞 8자리만 입력해도 된다.

## 파일

| 경로 | 내용 |
|---|---|
| `config.toml` | 수집 시각(22시), 수집 기간(15일), 정확도 가중치·기준값, DB·도시 목록 경로 |
| `data/weather.sqlite3` | `city`, `weather`(예보), `accuracy`(n일전 vs d0), `error_log`(수집 실패) |
| `logs/YYYY-MM.log` | 수집 결과와 실패 기록 (받은 도시가 없는 실행은 기록하지 않음) |
| `weather_code.json` | WMO 날씨 코드 → 카테고리, 이름(en/ko/ja) |
| `weather_severity.json` | WMO 날씨 코드 → 변동성 계산용 (x, y) 좌표 |

## 테스트

```bash
python3 -m unittest        # 네트워크 없이 1초 안에 끝남 (Flask가 없으면 웹 엔드포인트 테스트는 건너뜀)
```

## 웹 조회

| 모드 | 보기 |
|---|---|
| 달력 · 주 | 7일 × (당일 + 하루 전 ~ 14일 전), 고른 항목의 값과 색 |
| 달력 · 월 | 보통 달력. 칸마다 당일 날씨·기온과 14칸 띠 (하루 전 → 14일 전), 초록(변동 적음) → 빨강(많음) |
| 달력 · 연 | 화면 비율에 맞춰 4×3 / 3×4 / 6×2 …, 너무 작으면 스크롤. 날짜마다 변동 중앙값을 그 해 다른 날짜와 비교한 색 |
| 일간 (날짜 클릭) | 14일 전 → 당일 예보가 당일과 얼마나 달랐나, 그래프 / 표 |
| 그래프 | 1·2·4·8·16 분할 (분할마다 도시·항목, 커서는 모든 분할에 같이 표시), n일 전별 예보 선, 최고·최저기온 함께 보기. 점 단위 3시간 ~ 1달 선택 (최고는 최대·최저는 최소, 여러 날이면 평균 최고·최저). 휠 확대·축소, Shift+휠·끌기로 이동, 최대 2년 |

수집이 실패하면 상단에 ⚠ 알림이 뜬다. "확인"은 그 브라우저에만 저장된다 (DB 기록은 그대로).
언어는 상단에서 한국어 / English / 日本語. 언어 추가는 `web/static/i18n/`에 파일 하나 + `weather_code.json`에 이름 (PLAN.md 7.5).
Docker 없이 띄울 때: `pip install -r web/requirements.txt` 후 `flask --app web.app run`.

## 데이터 직접 보기

SQL로 볼 때는 `sqlite3`나 DB 뷰어를 쓴다.

```bash
sqlite3 -readonly -box data/weather.sqlite3 \
  "SELECT target_date, lead_days, weather, temp_max, temp_min, precip_mm, precip_prob
   FROM weather JOIN city USING (city_id)
   WHERE city.name = 'Osaka' AND slot = 'day' ORDER BY target_date, lead_days DESC"
```

월별 n일전 정확도 쿼리는 [PLAN.md 5.2](PLAN.md) 참고.
