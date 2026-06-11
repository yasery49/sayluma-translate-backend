# SayLuma Translation Backend

Self-hosted book translation service for SayLuma AI.

It exposes:

- `GET /health`
- `POST /translate`

The Android app sends selected book text to `/translate` first. If this endpoint is unavailable, the app can still fall back to the existing Gemini chat endpoint.

## Why this exists

Book translation should not consume Gemini chat quota. This service runs on your own server and keeps the Android contract stable while we improve the translation engine behind it.

## Translation engine

Default provider:

- `facebook/m2m100_418M`

Why this model:

- Better sentence-level translation quality than the first Argos-only backend.
- One model supports English, Turkish, German, Spanish, Italian, French, and Russian.
- Hugging Face lists the model license as MIT.

Fallback provider:

- Argos Translate

If M2M100 cannot load, the service can fall back to Argos so the endpoint does not fail completely.

## Local run

```powershell
cd translation-backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:TRANSLATION_PROVIDER="m2m100"
$env:ALLOW_ARGOS_FALLBACK="true"
uvicorn main:app --host 0.0.0.0 --port 10000
```

Test:

```powershell
curl -X POST http://localhost:10000/translate `
  -H "Content-Type: application/json" `
  -d "{\"text\":\"Ich brauche eine neue Winterjacke, weil das Wetter in Berlin langsam kaelter wird.\",\"sourceLanguage\":\"German\",\"targetLanguage\":\"Turkish\"}"
```

Expected response shape:

```json
{
  "translation": "...",
  "provider": "m2m100",
  "sourceLanguage": "de",
  "targetLanguage": "tr",
  "pivotLanguage": null
}
```

## Render deploy

Create or update the Render Web Service from this folder/repo.

Recommended settings:

- Runtime: Docker
- Dockerfile path: `Dockerfile`
- Instance: at least 1-2 GB RAM is recommended for M2M100

Recommended environment:

```text
TRANSLATION_PROVIDER=m2m100
M2M100_MODEL=facebook/m2m100_418M
M2M100_DEVICE=cpu
M2M100_NUM_BEAMS=3
M2M100_MAX_INPUT_TOKENS=256
M2M100_MAX_NEW_TOKENS=180
TORCH_NUM_THREADS=2
ALLOW_ARGOS_FALLBACK=true
PRELOAD_M2M100_ON_STARTUP=false
AUTO_INSTALL_MODELS=true
PRELOAD_ARGOS_ON_STARTUP=false
PRELOAD_LANGUAGE_PAIRS=en:tr,en:de,en:es,en:it,en:fr,en:ru,tr:en,tr:de,tr:es,tr:it,tr:fr,tr:ru,de:en,de:tr,de:es,de:it,de:fr,de:ru,es:en,es:tr,es:de,es:it,es:fr,es:ru,it:en,it:tr,it:de,it:es,it:fr,it:ru,fr:en,fr:tr,fr:de,fr:es,fr:it,fr:ru,ru:en,ru:tr,ru:de,ru:es,ru:it,ru:fr
```

Keep `PRELOAD_M2M100_ON_STARTUP=false` on Render unless you use a stronger instance. The first translation request will download/load the model and can take longer, but later requests are faster.

## Android URL

After deploy, set this Gradle property:

```properties
BACKEND_TRANSLATE_URL=https://YOUR-TRANSLATION-SERVICE.onrender.com/translate
```

Current SayLuma setup:

```properties
BACKEND_TRANSLATE_URL=https://sayluma-translate-backend.onrender.com/translate
```

## Notes

- This improves quality, but it is heavier than Argos.
- If Render free memory is too low, the service may restart when loading M2M100. In that case use a larger instance or switch `TRANSLATION_PROVIDER=argos` temporarily.
- First model download can be slow.
- For commercial release, keep a record of the model/license used by the deployed service.
