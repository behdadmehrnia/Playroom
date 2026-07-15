# Yar Kids standalone API
# Build from the repo root:
#   docker build -f api/Dockerfile -t yarkids-api .
#
# Run (mount textbook index + page images):
#   docker run --rm -p 8000:8000 \
#     -e YARKIDS_BACKEND_MODEL=… \
#     -e YARKIDS_LLM_API_KEY=… \
#     -e YARKIDS_LLM_BASE_URL=… \
#     -v /path/to/index.sqlite:/app/api/textbook/data/index.sqlite:ro \
#     -v /path/to/pages:/app/api/textbook/data/pages:ro \
#     yarkids-api

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

# Application package (prompts + textbook code + catalog metadata)
COPY api/ /app/api/

# Large artifacts (pages/, pdfs/, index.sqlite) are excluded via .dockerignore —
# mount them at runtime. Ensure expected dirs exist.
RUN mkdir -p \
        /app/api/textbook/data/pages \
        /app/api/textbook/data/pdfs \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Embedded textbook is the default (empty YARKIDS_TEXTBOOK_API_URL).
ENV YARKIDS_API_HOST=0.0.0.0 \
    YARKIDS_API_PORT=8000 \
    YARKIDS_ENABLE_TEXTBOOK_CONTEXT=true \
    TEXTBOOK_DATA_DIR=/app/api/textbook/data

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
