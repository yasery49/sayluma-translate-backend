# SayLuma Translation Backend

Self-hosted book translation service for SayLuma AI.

It exposes:

- `GET /health`
- `POST /translate`

The Android app sends selected book text to `/translate` first. If this endpoint is unavailable, the app can still fall back to the existing Gemini chat endpoint.

## Why this exists

Book translation should not consume Gemini chat quota. This service runs on your own server and keeps the Android contract stable while we improve the translation engine behind it.

## Translation engine

Default provider for this test build:

- `argos`

Why this test mode:

- We want to test Argos directly without ML Kit hiding the result.
- Argos is light enough for Render free instances.
- Android now calls the backend before ML Kit for book translations.

Optional provider:

- `marian`
- `facebook/m2m100_418M`

Marian/M2M100 need extra dependencies and more RAM. Keep this test build on `argos` while using Render free.

## Local run

```powershell
cd translation-backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:TRANSLATION_PROVIDER="argos"
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
  "provider": "argos",
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
- Instance: Render free is enough for an Argos test, though first model download can still be slow.

Recommended environment:

```text
TRANSLATION_PROVIDER=argos
ALLOW_ARGOS_FALLBACK=true
AUTO_INSTALL_MODELS=true
PRELOAD_ARGOS_ON_STARTUP=false
PRELOAD_LANGUAGE_PAIRS=en:tr,en:de,en:es,en:it,en:fr,en:ru,tr:en,tr:de,tr:es,tr:it,tr:fr,tr:ru,de:en,de:tr,de:es,de:it,de:fr,de:ru,es:en,es:tr,es:de,es:it,es:fr,es:ru,it:en,it:tr,it:de,it:es,it:fr,it:ru,fr:en,fr:tr,fr:de,fr:es,fr:it,fr:ru,ru:en,ru:tr,ru:de,ru:es,ru:it,ru:fr
```

Keep `PRELOAD_ARGOS_ON_STARTUP=false` on Render free. The first translation request will download/install the needed Argos model and can take longer.

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

- This test build is intentionally Argos-only in `requirements.txt`.
- If you later want Marian/M2M100 again, add `transformers`, `sentencepiece`, and `torch` back to `requirements.txt` and use a larger instance.
- First model download can be slow.
- For commercial release, keep a record of the model/license used by the deployed service.
