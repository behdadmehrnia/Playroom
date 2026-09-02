# Playroom standalone API
# Build & run (preferred — named volume keeps textbook data across rebuilds):
#   docker compose up -d --build
#
# Or plain docker (explicit volume):
#   docker build -t playroom-api .
#   docker run --rm -p 8000:8000 \
#     -e PLAYROOM_BACKEND_MODEL=… \
#     -e PLAYROOM_LLM_API_KEY=… \
#     -e PLAYROOM_LLM_BASE_URL=… \
#     -v playroom-textbook-data:/app/api/textbook/data \
#     playroom-api

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Minimal system libs (Pillow / multipart uploads)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements-runtime.txt /tmp/requirements-runtime.txt
RUN pip install --compile -r /tmp/requirements-runtime.txt \
    && rm /tmp/requirements-runtime.txt

# Application package (prompts + textbook code)
COPY api/ /app/api/

# Seed catalog metadata; entrypoint always refreshes these onto the volume
RUN mkdir -p /opt/playroom/textbook-seed \
    && cp /app/api/textbook/data/catalog.json /opt/playroom/textbook-seed/ \
    && cp /app/api/textbook/data/subject_topics.json /opt/playroom/textbook-seed/ \
    && mkdir -p \
        /app/api/textbook/data/pages \
        /app/api/textbook/data/pdfs \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Declares the mount point; compose / `-v` provides the real named volume.
VOLUME ["/app/api/textbook/data"]

EXPOSE 8000

# Embedded textbook is the default (empty PLAYROOM_TEXTBOOK_API_URL).
ENV PLAYROOM_API_HOST=0.0.0.0 \
    PLAYROOM_API_PORT=8000 \
    PLAYROOM_ENABLE_TEXTBOOK_CONTEXT=true \
    TEXTBOOK_DATA_DIR=/app/api/textbook/data

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
