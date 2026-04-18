"""Basic translation service using MyMemory API (free, no API key needed)."""
import requests
import os


class TranslationService:
    """Fallback translation using MyMemory free API."""

    def __init__(self):
        self.base_url = 'https://api.mymemory.translated.net/get'

    def translate(self, text, source_lang='en', target_lang='es'):
        """
        Translate text using MyMemory free translation API.

        Args:
            text: Text to translate
            source_lang: ISO 639-1 source language code (use 'autodetect' or '' for auto)
            target_lang: ISO 639-1 target language code

        Returns:
            Translated text string
        """
        if not text or not text.strip():
            return ''

        # Handle auto-detect: MyMemory uses 'autodetect' as source
        if not source_lang or source_lang == 'auto' or source_lang == 'autodetect':
            source_lang = 'autodetect'

        try:
            params = {
                'q': text,
                'langpair': f'{source_lang}|{target_lang}'
            }

            print(f"[MyMemory] Translating: '{text[:50]}...' ({source_lang} -> {target_lang})")

            response = requests.get(
                self.base_url,
                params=params,
                timeout=15
            )
            response.raise_for_status()
            result = response.json()

            status = result.get('responseStatus')
            if status == 200:
                translated = result.get('responseData', {}).get('translatedText', '')
                if translated:
                    # MyMemory sometimes returns the detected language
                    detected = result.get('responseData', {}).get('detectedLanguage', '')
                    if detected:
                        print(f"[MyMemory] Detected language: {detected}")
                    print(f"[MyMemory] Result: '{translated[:50]}...'")
                    return translated

            # If main result failed, check matches
            matches = result.get('matches', [])
            if matches:
                return matches[0].get('translation', text)

            print(f"[MyMemory] No translation found, status: {status}")
            return text

        except Exception as e:
            print(f"[MyMemory] Translation error: {e}")
            return text

    def detect_language(self, text):
        """Detect language using MyMemory auto-detect."""
        if not text:
            return 'en'

        try:
            params = {
                'q': text,
                'langpair': 'autodetect|en'
            }
            response = requests.get(self.base_url, params=params, timeout=10)
            result = response.json()
            detected = result.get('responseData', {}).get('detectedLanguage', '')
            if detected:
                return detected
        except Exception as e:
            print(f"[MyMemory] Detection error: {e}")

        return 'en'
