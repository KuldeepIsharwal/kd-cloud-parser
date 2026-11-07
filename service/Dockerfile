# Inference service image. Model weights are NOT in the image: they are downloaded
# from object storage (MODEL_URI) at start-up. CPU-only PyTorch wheel keeps it small.
# Build (from the repository root):  docker build -t kd-parser:1.0 -f service/Dockerfile .
FROM python:3.12.8-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HOME=/tmp

WORKDIR /app
COPY service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && find /usr/local/lib/python3.12 -name "__pycache__" -type d -prune -exec rm -rf {} +

COPY service/app.py /app/app.py
COPY data/schema.json /app/schema.json

USER 1000
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]
