# Tracking_Volatility

등록한 도시들의 15일 예보를 매일 **도시 현지 시각 22시**에 [Open-Meteo](https://open-meteo.com/)에서 받아 SQLite에 쌓고,
같은 날짜에 대한 예보가 14일 전부터 당일까지 얼마나 바뀌었는지(변동성)를 추적한다.
설계와 진행 상황은 [PLAN.md](PLAN.md) 참고.

## 요구 사항

- Python 3.11+ (표준 라이브러리만 사용)
- cron, `flock`, `timeout` (리눅스 기본)

## 시작하기

```bash
python3 -m accu_weather city add "Osaka"     # 영어 이름으로 검색 → 번호 선택
./run.sh install                             # crontab에 30분 간격으로 등록
```

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

./run.sh install | uninstall                                        # crontab 등록 / 해제
```

`<id>`는 `city list`에 나오는 UUID 앞 8자리만 입력해도 된다.

## 파일

| 경로 | 내용 |
|---|---|
| `config.toml` | 수집 시각(22시), 수집 기간(15일), DB·도시 목록 경로 |
| `data/weather.sqlite3` | 수집 데이터 (`city`, `weather`, `accuracy` 테이블) |
| `logs/YYYY-MM.log` | 수집 결과와 실패 기록 (받은 도시가 없는 실행은 기록하지 않음) |
| `weather_code.json` | WMO 날씨 코드 → 카테고리, 이름(en/ko/ja) |
| `weather_severity.json` | WMO 날씨 코드 → 변동성 계산용 (x, y) 좌표 |

## 데이터 보기

조회 화면은 아직 없다 (웹 조회 예정). 지금은 `sqlite3`나 DB 뷰어로 직접 본다.

```bash
sqlite3 -readonly -box data/weather.sqlite3 \
  "SELECT target_date, lead_days, weather, temp_max, temp_min, precip_mm, precip_prob
   FROM weather JOIN city USING (city_id)
   WHERE city.name = 'Osaka' AND slot = 'day' ORDER BY target_date, lead_days DESC"
```
