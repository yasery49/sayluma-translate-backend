import os
import re
import threading
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import argostranslate.package
import argostranslate.translate


app = FastAPI(title="SayLuma Translation Backend", version="1.0.0")

AUTO_INSTALL_MODELS = os.getenv("AUTO_INSTALL_MODELS", "true").lower() == "true"
PRELOAD_LANGUAGE_PAIRS = os.getenv(
    "PRELOAD_LANGUAGE_PAIRS",
    "de:tr,en:tr,tr:en,de:en,en:de,es:en,en:es,it:en,en:it,fr:en,en:fr,ru:en,en:ru",
)

_package_lock = threading.RLock()
_package_index_ready = False


class TranslateRequest(BaseModel):
    text: Optional[str] = Field(default=None, max_length=2500)
    sourceText: Optional[str] = Field(default=None, max_length=2500)
    sourceLanguage: Optional[str] = None
    targetLanguage: Optional[str] = None
    nativeLanguage: Optional[str] = None
    maxOutputWords: Optional[int] = Field(default=80, ge=1, le=220)


class TranslateResponse(BaseModel):
    translation: str
    provider: str = "argos"
    sourceLanguage: str
    targetLanguage: str
    pivotLanguage: Optional[str] = None


LANGUAGE_ALIASES = {
    "english": "en",
    "ingilizce": "en",
    "ingles": "en",
    "inglese": "en",
    "anglais": "en",
    "englisch": "en",
    "en": "en",
    "turkish": "tr",
    "turk": "tr",
    "turkce": "tr",
    "turkish": "tr",
    "turco": "tr",
    "turc": "tr",
    "tr": "tr",
    "german": "de",
    "deutsch": "de",
    "almanca": "de",
    "aleman": "de",
    "allemand": "de",
    "tedesco": "de",
    "de": "de",
    "spanish": "es",
    "espanol": "es",
    "ispanyolca": "es",
    "ispanyol": "es",
    "spanisch": "es",
    "spagnolo": "es",
    "espagnol": "es",
    "es": "es",
    "italian": "it",
    "italiano": "it",
    "italyanca": "it",
    "italienisch": "it",
    "italien": "it",
    "it": "it",
    "french": "fr",
    "francais": "fr",
    "fransizca": "fr",
    "fransiz": "fr",
    "frances": "fr",
    "francese": "fr",
    "franzosisch": "fr",
    "fr": "fr",
    "russian": "ru",
    "rusca": "ru",
    "rus": "ru",
    "russisch": "ru",
    "ru": "ru",
}


def normalize_language(language: Optional[str], fallback: Optional[str] = None) -> str:
    raw = (language or fallback or "").strip().lower()
    raw = (
        raw.replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
        .replace("ñ", "n")
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("ù", "u")
        .replace("ß", "ss")
    )
    raw = re.sub(r"[^a-z]+", " ", raw).strip()
    if raw in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[raw]
    for key, code in LANGUAGE_ALIASES.items():
        if key in raw:
            return code
    raise HTTPException(status_code=400, detail=f"Unsupported language: {language or fallback}")


def clean_text(text: str, max_words: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Text is empty.")
    words = clean.split()
    # Keep the request bounded. Long PDF chunks should be translated sentence by sentence.
    if len(words) > 220:
        clean = " ".join(words[:220])
    return clean


def limit_words(text: str, max_words: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    words = clean.split()
    if len(words) <= max_words:
        return clean
    return " ".join(words[:max_words]).rstrip(".,;:") + "..."


def refresh_package_index_once() -> None:
    global _package_index_ready
    if _package_index_ready:
        return
    with _package_lock:
        if _package_index_ready:
            return
        argostranslate.package.update_package_index()
        _package_index_ready = True


@lru_cache(maxsize=128)
def has_installed_pair(source_code: str, target_code: str) -> bool:
    installed_languages = argostranslate.translate.get_installed_languages()
    source_language = next((lang for lang in installed_languages if lang.code == source_code), None)
    if source_language is None:
        return False
    return any(lang.code == target_code for lang in source_language.translations_from)


def install_pair_if_available(source_code: str, target_code: str) -> bool:
    if has_installed_pair(source_code, target_code):
        return True
    if not AUTO_INSTALL_MODELS:
        return False

    with _package_lock:
        has_installed_pair.cache_clear()
        if has_installed_pair(source_code, target_code):
            return True
        refresh_package_index_once()
        packages = argostranslate.package.get_available_packages()
        package = next(
            (
                pkg
                for pkg in packages
                if pkg.from_code == source_code and pkg.to_code == target_code
            ),
            None,
        )
        if package is None:
            return False
        package_path = package.download()
        argostranslate.package.install_from_path(package_path)
        has_installed_pair.cache_clear()
        return has_installed_pair(source_code, target_code)


def translate_pair(text: str, source_code: str, target_code: str) -> str:
    if source_code == target_code:
        return text
    if not install_pair_if_available(source_code, target_code):
        raise HTTPException(
            status_code=503,
            detail=f"Translation model is not installed or available: {source_code}->{target_code}",
        )
    translated = argostranslate.translate.translate(text, source_code, target_code).strip()
    if not translated:
        raise HTTPException(status_code=502, detail="Translation model returned an empty result.")
    return translated


def translate_with_optional_pivot(text: str, source_code: str, target_code: str) -> tuple[str, Optional[str]]:
    if source_code == target_code:
        return text, None

    if install_pair_if_available(source_code, target_code):
        return translate_pair(text, source_code, target_code), None

    pivot = "en"
    if source_code != pivot and target_code != pivot:
        if install_pair_if_available(source_code, pivot) and install_pair_if_available(pivot, target_code):
            intermediate = translate_pair(text, source_code, pivot)
            return translate_pair(intermediate, pivot, target_code), pivot

    raise HTTPException(
        status_code=503,
        detail=f"No direct or English-pivot translation model available: {source_code}->{target_code}",
    )


def preload_models() -> None:
    if not AUTO_INSTALL_MODELS:
        return
    for item in PRELOAD_LANGUAGE_PAIRS.split(","):
        pair = item.strip()
        if not pair or ":" not in pair:
            continue
        source_code, target_code = pair.split(":", 1)
        try:
            install_pair_if_available(source_code.strip(), target_code.strip())
        except Exception as error:
            print(f"Model preload skipped for {pair}: {error}", flush=True)


@app.on_event("startup")
def on_startup() -> None:
    # Render and similar hosts can start faster if model downloads are lazy.
    if os.getenv("PRELOAD_ON_STARTUP", "false").lower() == "true":
        preload_models()


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "provider": "argos",
        "autoInstallModels": AUTO_INSTALL_MODELS,
    }


@app.post("/translate", response_model=TranslateResponse)
def translate(request: TranslateRequest) -> TranslateResponse:
    source_text = request.text or request.sourceText or ""
    source_code = normalize_language(request.sourceLanguage, "English")
    target_code = normalize_language(request.targetLanguage, request.nativeLanguage)
    max_words = request.maxOutputWords or 80

    clean = clean_text(source_text, max_words=max_words)
    translated, pivot = translate_with_optional_pivot(clean, source_code, target_code)

    return TranslateResponse(
        translation=limit_words(translated, max_words=max_words),
        sourceLanguage=source_code,
        targetLanguage=target_code,
        pivotLanguage=pivot,
    )
