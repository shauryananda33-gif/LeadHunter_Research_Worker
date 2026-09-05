FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates wget gnupg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
RUN playwright install --with-deps chromium
COPY . .
EXPOSE 10000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
