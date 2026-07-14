# Single-container multi-service Dockerfile for Yar Kids
# Runs both textbook-service (port 8080) and yarkids-api (port 8000) via supervisor

FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies for both services
COPY requirements.txt .
COPY api/requirements.txt api/requirements.txt
COPY textbook-service/requirements.txt textbook-service/requirements.txt
COPY textbook-service/requirements-indexer.txt textbook-service/requirements-indexer.txt

RUN pip install --no-cache-dir --prefix=/install \
    -r requirements.txt \
    -r api/requirements.txt \
    -r textbook-service/requirements.txt \
    -r textbook-service/requirements-indexer.txt

# Runtime stage
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tesseract-ocr \
    tesseract-ocr-fas \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY pipe.py .
COPY prompts/ ./prompts/
COPY api/ ./api/
COPY scripts/ ./scripts/
COPY textbook-service/app/ ./textbook-service/app/
COPY textbook-service/indexer/ ./textbook-service/indexer/
COPY textbook-service/data/ ./textbook-service/data/

# Supervisor config to run both services
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create non-root user
RUN useradd --no-create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app /var/log/supervisor /var/run/supervisor
USER appuser

EXPOSE 8000 8080

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]