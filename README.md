# SayLuma Translation Backend

Self-hosted book translation service for SayLuma AI.

It exposes a Gemini-compatible lightweight endpoint:

- `GET /health`
- `POST /translate`

The Android app sends selected book text to `/translate` first. If this endpoint is unavailable, the app can still fall back to the existing Gemini chat endpoint.

## Why this exists

Book translation should not consume Gemini chat quota. This service uses open-source Argos Translate models and runs on your own server.

## Local run

```powershell
cd translation-backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:AUTO_INSTALL_MODELS="true"
uvicorn main:app --host 0.0.0.0 --port 10000
```

Test:

```powershell
curl -X POST http://localhost:10000/translate `
  -H "Content-Type: application/json" `
  -d "{\"text\":\"Ich brauche eine neue Winterjacke.\",\"sourceLanguage\":\"German\",\"targetLanguage\":\"Turkish\"}"
```

Expected response shape:

```json
{
  "translation": "...",
  "provider": "argos",
  "sourceLanguage": "de",
  "targetLanguage": "tr",
  "pivotLanguage": "en"
}
```

## Render deploy

Create a new Render Web Service from this folder.

Recommended settings:

- Runtime: Docker
- Root Directory: `translation-backend`
- Environment:
  - `AUTO_INSTALL_MODELS=true`
  - `PRELOAD_ON_STARTUP=false`
  - `PRELOAD_LANGUAGE_PAIRS=de:tr,en:tr,tr:en,de:en,en:de,es:en,en:es,it:en,en:it,fr:en,en:fr,ru:en,en:ru`

If model downloads make the first request slow, set `PRELOAD_ON_STARTUP=true`.

## Android URL

After deploy, set this Gradle property:

```properties
BACKEND_TRANSLATE_URL=https://YOUR-TRANSLATION-SERVICE.onrender.com/translate
```

If you deploy the route into the existing backend, use:

```properties
BACKEND_TRANSLATE_URL=https://simli-tts-backend.onrender.com/translate
```

## Notes

- This removes Gemini/Groq cost for premium book translation requests, but hosting still has a cost.
- First translation for a language pair can be slow because the model may be downloaded.
- If a direct pair is unavailable, the service tries English as a pivot, for example German -> English -> Turkish.
- For commercial use, check the license of every installed Argos package/model before release.
