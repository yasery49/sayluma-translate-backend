import os
import re
import threading
import unicodedata
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import argostranslate.package
import argostranslate.translate


app = FastAPI(title="SayLuma Translation Backend", version="2.0.0")

TRANSLATION_PROVIDER = os.getenv("TRANSLATION_PROVIDER", "m2m100").strip().lower()
ALLOW_ARGOS_FALLBACK = os.getenv("ALLOW_ARGOS_FALLBACK", "true").lower() == "true"

M2M100_MODEL_NAME = os.getenv("M2M100_MODEL", "facebook/m2m100_418M")
M2M100_DEVICE = os.getenv("M2M100_DEVICE", "cpu").strip().lower()
M2M100_NUM_BEAMS = int(os.getenv("M2M100_NUM_BEAMS", "3"))
M2M100_MAX_INPUT_TOKENS = int(os.getenv("M2M100_MAX_INPUT_TOKENS", "256"))
M2M100_MAX_NEW_TOKENS = int(os.getenv("M2M100_MAX_NEW_TOKENS", "180"))
M2M100_REPETITION_PENALTY = float(os.getenv("M2M100_REPETITION_PENALTY", "1.08"))
TORCH_NUM_THREADS = int(os.getenv("TORCH_NUM_THREADS", "2"))

AUTO_INSTALL_MODELS = os.getenv("AUTO_INSTALL_MODELS", "true").lower() == "true"
PRELOAD_LANGUAGE_PAIRS = os.getenv(
    "PRELOAD_LANGUAGE_PAIRS",
    "de:tr,en:tr,tr:en,de:en,en:de,es:en,en:es,it:en,en:it,fr:en,en:fr,ru:en,en:ru",
)

_package_lock = threading.RLock()
_package_index_ready = False

_m2m_lock = threading.RLock()
_m2m_tokenizer = None
_m2m_model = None
_m2m_torch = None
_m2m_device = "cpu"


class TranslateRequest(BaseModel):
    text: Optional[str] = Field(default=None, max_length=2500)
    sourceText: Optional[str] = Field(default=None, max_length=2500)
    sourceLanguage: Optional[str] = None
    targetLanguage: Optional[str] = None
    nativeLanguage: Optional[str] = None
    maxOutputWords: Optional[int] = Field(default=80, ge=1, le=220)


class TranslateResponse(BaseModel):
    translation: str
    provider: str
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


def fold_to_ascii(value: str) -> str:
    value = (
        value.replace("ı", "i")
        .replace("İ", "i")
        .replace("ğ", "g")
        .replace("Ğ", "g")
        .replace("ü", "u")
        .replace("Ü", "u")
        .replace("ş", "s")
        .replace("Ş", "s")
        .replace("ö", "o")
        .replace("Ö", "o")
        .replace("ç", "c")
        .replace("Ç", "c")
        .replace("ß", "ss")
    )
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def normalize_language(language: Optional[str], fallback: Optional[str] = None) -> str:
    raw = (language or fallback or "").strip().lower()
    raw = (
        raw.replace("Ä±", "i")
        .replace("ÄŸ", "g")
        .replace("Ã¼", "u")
        .replace("ÅŸ", "s")
        .replace("Ã¶", "o")
        .replace("Ã§", "c")
        .replace("Ã±", "n")
        .replace("Ã©", "e")
        .replace("Ã¨", "e")
        .replace("Ãª", "e")
        .replace("Ã ", "a")
        .replace("Ã¹", "u")
        .replace("ÃŸ", "ss")
    )
    raw = fold_to_ascii(raw)
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


def split_for_translation(text: str, max_chars: int = 700) -> list[str]:
    # Avoid splitting dates such as "31. Oktober" by requiring the char before
    # the sentence punctuation not to be a digit.
    sentence_parts = re.split(r"(?<!\d)(?<=[.!?])\s+", text)
    segments: list[str] = []
    for part in sentence_parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_chars:
            segments.append(part)
            continue

        current: list[str] = []
        current_len = 0
        for word in part.split():
            next_len = current_len + len(word) + (1 if current else 0)
            if current and next_len > max_chars:
                segments.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len = next_len
        if current:
            segments.append(" ".join(current))
    return segments or [text]


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


def translate_pair_argos(text: str, source_code: str, target_code: str) -> str:
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


def translate_with_argos_pivot(text: str, source_code: str, target_code: str) -> tuple[str, Optional[str]]:
    if source_code == target_code:
        return text, None

    if install_pair_if_available(source_code, target_code):
        return translate_pair_argos(text, source_code, target_code), None

    pivot = "en"
    if source_code != pivot and target_code != pivot:
        if install_pair_if_available(source_code, pivot) and install_pair_if_available(pivot, target_code):
            intermediate = translate_pair_argos(text, source_code, pivot)
            return translate_pair_argos(intermediate, pivot, target_code), pivot

    raise HTTPException(
        status_code=503,
        detail=f"No direct or English-pivot translation model available: {source_code}->{target_code}",
    )


def load_m2m100() -> None:
    global _m2m_tokenizer, _m2m_model, _m2m_torch, _m2m_device
    if _m2m_tokenizer is not None and _m2m_model is not None:
        return

    with _m2m_lock:
        if _m2m_tokenizer is not None and _m2m_model is not None:
            return

        try:
            import torch
            from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
        except Exception as error:
            raise RuntimeError(f"M2M100 dependencies are not installed: {error}") from error

        if TORCH_NUM_THREADS > 0:
            torch.set_num_threads(TORCH_NUM_THREADS)

        tokenizer = M2M100Tokenizer.from_pretrained(M2M100_MODEL_NAME)
        model = M2M100ForConditionalGeneration.from_pretrained(M2M100_MODEL_NAME)

        if M2M100_DEVICE == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = M2M100_DEVICE

        model.to(device)
        model.eval()

        _m2m_torch = torch
        _m2m_tokenizer = tokenizer
        _m2m_model = model
        _m2m_device = device


def translate_segment_m2m100(text: str, source_code: str, target_code: str) -> str:
    load_m2m100()

    with _m2m_lock:
        tokenizer = _m2m_tokenizer
        model = _m2m_model
        torch = _m2m_torch

        tokenizer.src_lang = source_code
        try:
            forced_bos_token_id = tokenizer.get_lang_id(target_code)
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"M2M100 does not support target language: {target_code}") from error

        encoded = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=M2M100_MAX_INPUT_TOKENS,
        )
        encoded = {key: value.to(_m2m_device) for key, value in encoded.items()}

        with torch.no_grad():
            generated_tokens = model.generate(
                **encoded,
                forced_bos_token_id=forced_bos_token_id,
                max_new_tokens=M2M100_MAX_NEW_TOKENS,
                num_beams=M2M100_NUM_BEAMS,
                no_repeat_ngram_size=3,
                repetition_penalty=M2M100_REPETITION_PENALTY,
                early_stopping=True,
            )
        translated = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0].strip()

    if not translated:
        raise HTTPException(status_code=502, detail="M2M100 returned an empty result.")
    return translated


def translate_with_m2m100(text: str, source_code: str, target_code: str) -> str:
    if source_code == target_code:
        return text

    translated_segments = [
        translate_segment_m2m100(segment, source_code, target_code)
        for segment in split_for_translation(text)
    ]
    return re.sub(r"\s+", " ", " ".join(translated_segments)).strip()


def translate_best(text: str, source_code: str, target_code: str) -> tuple[str, str, Optional[str]]:
    if TRANSLATION_PROVIDER == "argos":
        translated, pivot = translate_with_argos_pivot(text, source_code, target_code)
        return translated, "argos", pivot

    try:
        translated = translate_with_m2m100(text, source_code, target_code)
        return translated, "m2m100", None
    except Exception as error:
        if not ALLOW_ARGOS_FALLBACK:
            if isinstance(error, HTTPException):
                raise error
            raise HTTPException(status_code=503, detail=f"M2M100 translation failed: {error}") from error
        print(f"M2M100 failed, falling back to Argos: {error}", flush=True)
        translated, pivot = translate_with_argos_pivot(text, source_code, target_code)
        return translated, "argos-fallback", pivot


def preload_argos_models() -> None:
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
            print(f"Argos model preload skipped for {pair}: {error}", flush=True)


@app.on_event("startup")
def on_startup() -> None:
    if os.getenv("PRELOAD_M2M100_ON_STARTUP", "false").lower() == "true":
        try:
            load_m2m100()
        except Exception as error:
            print(f"M2M100 preload skipped: {error}", flush=True)
    if os.getenv("PRELOAD_ARGOS_ON_STARTUP", "false").lower() == "true":
        preload_argos_models()


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "provider": TRANSLATION_PROVIDER,
        "model": M2M100_MODEL_NAME if TRANSLATION_PROVIDER != "argos" else "argos",
        "m2m100Loaded": _m2m_model is not None,
        "argosFallback": ALLOW_ARGOS_FALLBACK,
        "autoInstallArgosModels": AUTO_INSTALL_MODELS,
    }


@app.post("/translate", response_model=TranslateResponse)
def translate(request: TranslateRequest) -> TranslateResponse:
    source_text = request.text or request.sourceText or ""
    source_code = normalize_language(request.sourceLanguage, "English")
    target_code = normalize_language(request.targetLanguage, request.nativeLanguage)
    max_words = request.maxOutputWords or 80

    clean = clean_text(source_text, max_words=max_words)
    translated, provider, pivot = translate_best(clean, source_code, target_code)

    return TranslateResponse(
        translation=limit_words(translated, max_words=max_words),
        provider=provider,
        sourceLanguage=source_code,
        targetLanguage=target_code,
        pivotLanguage=pivot,
    )
