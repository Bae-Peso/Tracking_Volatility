# 수집기 이미지. 컨테이너가 뜨면 `python3 -m accu_weather serve`가 매 :00/:30에 collect를 돌린다.
# 빌드 후 확인: docker compose run --rm --entrypoint python3 collector -c "import curses, zoneinfo; print(zoneinfo.ZoneInfo('Asia/Tokyo'))"
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    ACCU_WEATHER_DOCKER=1

# zoneinfo가 쓸 시간대 데이터 (slim 이미지에는 시스템 tzdata가 없을 수 있다)
RUN pip install --no-cache-dir tzdata

WORKDIR /app
COPY accu_weather/ accu_weather/
COPY weather_code.json weather_severity.json config.toml ./

# `docker compose run --rm collector setup` 처럼 뒤에 붙인 명령이 serve 대신 들어간다
ENTRYPOINT ["python3", "-m", "accu_weather"]
CMD ["serve"]
