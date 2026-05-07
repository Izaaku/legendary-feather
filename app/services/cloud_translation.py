"""Translation service using DeepL API (cloud).

Drop-in replacement for TranslationService (MyMemory).
DeepL free tier: 500,000 chars/month. Pro: unlimited.

Requires: pip install deepl
Env: DEEPL_API_KEY
"""
import os

import deepl


# DeepL uses specific language codes (some differ from ISO 639-1)
_DEEPL_SOURCE_MAP = {
    'en': 'EN', 'es': 'ES', 'fr': 'FR', 'de': 'DE', 'it': 'IT',
    'pt': 'PT', 'nl': 'NL', 'pl': 'PL', 'ru': 'RU', 'ja': 'JA',
    'zh': 'ZH', 'ko': 'KO', 'ar': 'AR', 'cs': 'CS', 'da': 'DA',
    'el': 'EL', 'fi': 'FI', 'hu': 'HU', 'id': 'ID', 'lt': 'LT',
    'lv': 'LV', 'nb': 'NB', 'no': 'NB', 'ro': 'RO', 'sk': 'SK',
    'sl': 'SL', 'sv': 'SV', 'tr': 'TR', 'uk': 'UK', 'bg': 'BG',
    'et': 'ET',
}

_DEEPL_TARGET_MAP = {
    'en': 'EN-US', 'es': 'ES', 'fr': 'FR', 'de': 'DE', 'it': 'IT',
    'pt': 'PT-BR', 'nl': 'NL', 'pl': 'PL', 'ru': 'RU', 'ja': 'JA',
    'zh': 'ZH-HANS', 'ko': 'KO', 'ar': 'AR', 'cs': 'CS', 'da': 'DA',
    'el': 'EL', 'fi': 'FI', 'hu': 'HU', 'id': 'ID', 'lt': 'LT',
    'lv': 'LV', 'nb': 'NB', 'no': 'NB', 'ro': 'RO', 'sk': 'SK',
    'sl': 'SL', 'sv': 'SV', 'tr': 'TR', 'uk': 'UK', 'bg': 'BG',
    'et': 'ET',
}


class CloudTranslationService:
    """Cloud-based translation using DeepL API."""

    def __init__(self):
        self.api_key = os.getenv('DEEPL_API_KEY', '')
        self.translator = deepl.Translator(self.api_key) if self.api_key else None

        # Fallback to MyMemory for unsupported languages
        self._fallback = None

        if self.api_key:
            print('[CloudTranslation] DeepL API ready.')
        else:
            print('[CloudTranslation] DEEPL_API_KEY not set — using MyMemory fallback.')

    def _get_fallback(self):
        """Lazy-load MyMemory fallback for unsupported languages."""
        if self._fallback is None:
            from app.services.translation import TranslationService
            self._fallback = TranslationService()
        return self._fallback

    def _to_deepl_source(self, lang_code):
        """Convert ISO 639-1 to DeepL source language code."""
        if not lang_code:
            return None
        return _DEEPL_SOURCE_MAP.get(lang_code.lower(), lang_code.upper())

    def _to_deepl_target(self, lang_code):
        """Convert ISO 639-1 to DeepL target language code."""
        if not lang_code:
            return 'EN-US'
        return _DEEPL_TARGET_MAP.get(lang_code.lower(), lang_code.upper())

    def translate(self, text, source_lang='en', target_lang='es'):
        """
        Translate text using DeepL API, with MyMemory fallback.

        Args:
            text: Text to translate
            source_lang: ISO 639-1 source language code ('auto'/'autodetect' for auto)
            target_lang: ISO 639-1 target language code

        Returns:
            Translated text string
        """
        if not text or not text.strip():
            return ''

        # Auto-detect: set source to None for DeepL
        auto_detect = (not source_lang or source_lang in ('auto', 'autodetect'))

        # If DeepL not configured, use fallback
        if not self.translator:
            fb = self._get_fallback()
            return fb.translate(text, source_lang, target_lang)

        try:
            deepl_source = None if auto_detect else self._to_deepl_source(source_lang)
            deepl_target = self._to_deepl_target(target_lang)

            print(f'[DeepL] Translating: "{text[:50]}..." '
                  f'({deepl_source or "auto"} -> {deepl_target})')

            result = self.translator.translate_text(
                text,
                source_lang=deepl_source,
                target_lang=deepl_target
            )

            translated = result.text
            detected = result.detected_source_lang

            print(f'[DeepL] Detected: {detected} | Result: "{translated[:50]}..."')
            try:
                from app.routes.admin import track_api_cost
                track_api_cost('deepl', chars=len(text or ''))
            except Exception:
                pass
            return translated

        except deepl.DeepLException as e:
            error_msg = str(e)
            # If language not supported by DeepL, fall back to MyMemory
            if 'not supported' in error_msg.lower() or 'target_lang' in error_msg.lower():
                print(f'[DeepL] Language not supported, falling back to MyMemory: {e}')
                fb = self._get_fallback()
                return fb.translate(text, source_lang, target_lang)

            print(f'[DeepL] Translation error: {e}')
            # Fall back to MyMemory on any DeepL error
            fb = self._get_fallback()
            return fb.translate(text, source_lang, target_lang)

    def translate_batch(self, texts, source_lang='en', target_lang='es'):
        """Translate a list of strings in a SINGLE DeepL request.

        DeepL's translate_text() accepts a list and returns a list of results
        in one HTTP call. This is 10-20x faster than calling translate() in a
        loop, especially for the dashboard i18n which sends ~50-100 strings
        on every page load.

        Args:
            texts: list[str] — strings to translate (empties returned as '')
            source_lang: ISO 639-1 source code ('auto' for auto-detect)
            target_lang: ISO 639-1 target code

        Returns:
            list[str] — same length as `texts`, '' for empty inputs
        """
        if not texts:
            return []
        # Filter empties but remember positions so we can put '' back in place.
        non_empty = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
        out = [''] * len(texts)
        if not non_empty:
            return out

        if not self.translator:
            # No DeepL configured — translate each via fallback (which is itself
            # one-by-one but unavoidable without paid API).
            fb = self._get_fallback()
            for i, t in non_empty:
                try: out[i] = fb.translate(t, source_lang, target_lang)
                except Exception: out[i] = t
            return out

        auto_detect = (not source_lang or source_lang in ('auto', 'autodetect'))
        deepl_source = None if auto_detect else self._to_deepl_source(source_lang)
        deepl_target = self._to_deepl_target(target_lang)

        try:
            results = self.translator.translate_text(
                [t for _, t in non_empty],
                source_lang=deepl_source,
                target_lang=deepl_target,
            )
            # results is a list of TextResult objects (or a single one if input
            # was a single string — we always pass a list here so it's always
            # a list).
            for (i, t), r in zip(non_empty, results):
                out[i] = (r.text if r else t) or t
            try:
                from app.routes.admin import track_api_cost
                total_chars = sum(len(t or '') for _, t in non_empty)
                track_api_cost('deepl', chars=total_chars)
            except Exception:
                pass
            return out
        except Exception as e:
            print(f'[DeepL] Batch error, falling back per-string: {e}')
            fb = self._get_fallback()
            for i, t in non_empty:
                try: out[i] = fb.translate(t, source_lang, target_lang)
                except Exception: out[i] = t
            return out

        except Exception as e:
            print(f'[DeepL] Unexpected error: {e}')
            fb = self._get_fallback()
            return fb.translate(text, source_lang, target_lang)

    def detect_language(self, text):
        """Detect language using DeepL (translate to EN and check detected_source_lang)."""
        if not text or not self.translator:
            if not self.translator:
                fb = self._get_fallback()
                return fb.detect_language(text)
            return 'en'

        try:
            # DeepL detects language as a side effect of translation
            result = self.translator.translate_text(
                text[:100],  # Only need a short sample
                target_lang='EN-US'
            )
            detected = result.detected_source_lang.lower()
            print(f'[DeepL] Detected language: {detected}')
            return detected

        except Exception as e:
            print(f'[DeepL] Detection error: {e}')
            fb = self._get_fallback()
            return fb.detect_language(text)

    def health_check(self):
        """Check if DeepL API is reachable."""
        if not self.translator:
            return False
        try:
            usage = self.translator.get_usage()
            print(f'[DeepL] Usage: {usage.character.count}/{usage.character.limit} chars')
            return True
        except Exception:
            return False
