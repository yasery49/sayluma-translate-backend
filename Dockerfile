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
ENV TRANSLATION_PROVIDER=marian
ENV MARIAN_DEVICE=cpu
ENV MARIAN_NUM_BEAMS=4
ENV MARIAN_MAX_INPUT_TOKENS=256
ENV MARIAN_MAX_NEW_TOKENS=180
ENV MARIAN_MAX_CACHED_MODELS=1
ENV MARIAN_EN_TR_MODEL=Helsinki-NLP/opus-mt-en-trk
ENV MARIAN_EN_TR_PREFIX=">>tur<<"
ENV PRELOAD_MARIAN_ON_STARTUP=false
ENV M2M100_MODEL=facebook/m2m100_418M
ENV M2M100_DEVICE=cpu
ENV M2M100_NUM_BEAMS=3
ENV M2M100_MAX_INPUT_TOKENS=256
ENV M2M100_MAX_NEW_TOKENS=180
ENV TORCH_NUM_THREADS=2
ENV ALLOW_ARGOS_FALLBACK=true
ENV AUTO_INSTALL_MODELS=true
ENV PRELOAD_M2M100_ON_STARTUP=false
ENV PRELOAD_ARGOS_ON_STARTUP=false
ENV PRELOAD_LANGUAGE_PAIRS=en:tr,en:de,en:es,en:it,en:fr,en:ru,tr:en,tr:de,tr:es,tr:it,tr:fr,tr:ru,de:en,de:tr,de:es,de:it,de:fr,de:ru,es:en,es:tr,es:de,es:it,es:fr,es:ru,it:en,it:tr,it:de,it:es,it:fr,it:ru,fr:en,fr:tr,fr:de,fr:es,fr:it,fr:ru,ru:en,ru:tr,ru:de,ru:es,ru:it,ru:fr

EXPOSE 10000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
