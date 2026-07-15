# CPU-only optimized single-stage build
FROM python:3.12-slim

# Install system deps in one layer (cached)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fas \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt requirements-indexer.txt ./

# Install CPU-only PyTorch + all deps in one pip call (faster, better dep resolution)
# Use --no-deps for torch to avoid re-downloading, compile bytecode
RUN pip install --no-cache-dir --compile \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir --compile -r requirements-indexer.txt

# Copy application code
COPY app ./app
COPY indexer ./indexer
COPY data ./data

ENV TEXTBOOK_DATA_DIR=/app/data
ENV TEXTBOOK_HOST=0.0.0.0
ENV TEXTBOOK_PORT=8080

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
