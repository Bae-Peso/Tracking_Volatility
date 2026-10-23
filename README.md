# Tracking_Volatility

등록한 도시들의 15일 예보를 매일 **도시 현지 시각 22시**에 [Open-Meteo](https://open-meteo.com/)에서 받아 SQLite에 저장하고,
날짜마다 "n일 전(1~14) 예보가 당일 22시 예보(d0)와 얼마나 같았나"를 쌓는다.
결과는 일별로 그대로 보거나, 주별·월별·연도별로 같은 n일전끼리 평균 내어 본다 (조회 화면은 웹으로 추가 예정).
설계와 진행 상황은 [PLAN.md](PLAN.md) 참고.

## 요구 사항

- Python 3.11+ (표준 라이브러리만 사용, 설치 화면은 `curses`)
- Docker로 돌리면 위 둘 다 이미지 안에 있다. Docker 없이 돌리면 cron, `flock`, `timeout` (리눅스 기본)

## 시작하기 (Docker, 권장)

일반 리눅스 PC에 Docker Engine과 compose 플러그인이 있으면 된다.

```bash
printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env   # 컨테이너가 data/ 에 쓸 수 있게 (처음 한 번)
docker compose run --rm collector setup      # 설치 TUI: 언어 → 소개 → 자동 실행 안내 → 도시 추가 → 설치
docker compose up -d --build                 # 수집 컨테이너 시작 (재부팅 후 자동 재시작)
docker compose logs -f collector             # 로그
```

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
python3 -m unittest        # 네트워크 없이 1초 안에 끝남
```

## 데이터 보기

조회 화면은 아직 없다 (웹 조회 예정). 지금은 `sqlite3`나 DB 뷰어로 직접 본다.

```bash
sqlite3 -readonly -box data/weather.sqlite3 \
  "SELECT target_date, lead_days, weather, temp_max, temp_min, precip_mm, precip_prob
   FROM weather JOIN city USING (city_id)
   WHERE city.name = 'Osaka' AND slot = 'day' ORDER BY target_date, lead_days DESC"
```

월별 n일전 정확도 쿼리는 [PLAN.md 5.2](PLAN.md) 참고.
