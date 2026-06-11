FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV PORT=10000
ENV AUTO_INSTALL_MODELS=true
ENV PRELOAD_LANGUAGE_PAIRS=de:tr,en:tr,tr:en,de:en,en:de,es:en,en:es,it:en,en:it,fr:en,en:fr,ru:en,en:ru

EXPOSE 10000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
