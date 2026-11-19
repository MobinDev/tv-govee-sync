FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g 1000 -M -s /usr/sbin/nologin appuser

WORKDIR /app
COPY --chown=1000:1000 sync.py /app/sync.py

USER 1000:1000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD [ -f /tmp/heartbeat ] && [ $(( $(date +%s) - $(stat -c %Y /tmp/heartbeat) )) -lt 30 ]

CMD ["python", "/app/sync.py"]
