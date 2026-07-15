# Single-stage CPU-only optimized image running both services
FROM python:3.12-slim

# Install system dependencies in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fas \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt ./
COPY api/requirements.txt ./api/requirements.txt
COPY textbook_service/requirements.txt ./textbook_service/requirements.txt
COPY textbook_service/requirements-indexer.txt ./textbook_service/requirements-indexer.txt

# Install CPU-only PyTorch + all Python deps in one pip call
RUN pip install --no-cache-dir --compile \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir --compile \
    -r requirements.txt \
    -r api/requirements.txt \
    -r textbook_service/requirements.txt \
    -r textbook_service/requirements-indexer.txt

# Copy application code
COPY pipe.py ./
COPY pipe_api.py ./
COPY prompts ./prompts
COPY api ./api
COPY textbook_service ./textbook_service
COPY scripts ./scripts

VOLUME ["/app/textbook_service/data"]

ENV PYTHONPATH=/app
ENV TEXTBOOK_DATA_DIR=/app/textbook_service/data
ENV TEXTBOOK_HOST=0.0.0.0
ENV TEXTBOOK_PORT=8080

EXPOSE 8000 8080

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]