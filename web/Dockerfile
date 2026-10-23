# 웹 조회 이미지. gunicorn이 web.app을 8000번에서 띄우고, 앞단 nginx가 HTTP 포트로 받아 넘겨준다.
# 빌드 문맥은 저장소 루트 (compose.yaml의 web 서비스).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

COPY web/requirements.txt /tmp/requirements.txt
# tzdata: 도시 현지 "오늘" 계산용 (slim 이미지에는 시스템 tzdata가 없을 수 있다)
RUN pip install --no-cache-dir tzdata -r /tmp/requirements.txt

WORKDIR /app
COPY accu_weather/ accu_weather/
COPY web/ web/
COPY weather_code.json weather_weight.json config.toml ./

EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "web.app:create_app()"]
