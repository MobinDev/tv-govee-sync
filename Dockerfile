FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g 1000 -M -s /usr/sbin/nologin appuser

WORKDIR /app
COPY --chown=1000:1000 sync.py /app/sync.py

USER 1000:1000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, time; raise SystemExit(0 if time.time() - os.path.getmtime('/tmp/heartbeat') < 30 else 1)"

CMD ["python", "/app/sync.py"]
