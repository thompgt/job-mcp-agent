FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system deps required by some NLP and PDF libs
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential tesseract-ocr poppler-utils libgl1 libmupdf-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements from repo root (compose will build with repo root as context)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy repository into container
COPY . /app

EXPOSE 8002

# Run FastAPI app
CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8002"]
