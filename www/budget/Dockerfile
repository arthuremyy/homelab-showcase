FROM python:3.12.16-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY frontend/ frontend/

EXPOSE 8700
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8700/api/budget/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8700"]
