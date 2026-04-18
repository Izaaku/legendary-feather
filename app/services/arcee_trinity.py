"""Advanced translation service using Arcee Trinity."""
import requests
import os


class ArceeTrinity:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv('ARCEE_API_KEY')
        self.base_url = 'https://api.arcee-ai.com/v1/chat/generative'

    def translate(self, text, source_lang, target_lang, context=''):
        """
        Translate text using Arcee Trinity for complex/nuanced translations.

        Args:
            text: Text to translate
            source_lang: Source language name (e.g., 'English')
            target_lang: Target language name (e.g., 'Spanish')
            context: Optional context for better translation

        Returns:
            Translated text string
        """
        if not self.api_key:
            print("[Arcee] No API key configured")
            return text

        if not text or not text.strip():
            return ''

        context_note = f"\nContext: {context}" if context else ""

        prompt = (
            f"Translate the following text from {source_lang} to {target_lang}. "
            f"Maintain the exact meaning, tone, and context. "
            f"Return ONLY the translated text, nothing else.{context_note}\n\n"
            f"Text: {text}"
        )

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'model': 'Trinity-Large',
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.3,
            'max_tokens': 2000
        }

        try:
            response = requests.post(
                self.base_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()

            if result.get('choices') and result['choices'][0].get('message'):
                return result['choices'][0]['message']['content'].strip()

            return text

        except requests.exceptions.Timeout:
            print("[Arcee] Request timed out")
            return text
        except Exception as e:
            print(f"[Arcee] Error: {e}")
            return text

    def detect_language(self, text):
        """Detect the language of input text."""
        if not self.api_key or not text:
            return 'en'

        prompt = (
            f"Detect the language of this text and return ONLY the ISO 639-1 "
            f"language code (e.g., 'en', 'es', 'fr'). Text: {text}"
        )

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'model': 'Trinity-Large',
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.1,
            'max_tokens': 10
        }

        try:
            response = requests.post(
                self.base_url, json=payload, headers=headers, timeout=10
            )
            result = response.json()
            if result.get('choices'):
                lang = result['choices'][0]['message']['content'].strip().lower()[:2]
                return lang
        except Exception as e:
            print(f"[Arcee] Language detection error: {e}")

        return 'en'

    def health_check(self):
        """Check if Arcee API is reachable."""
        try:
            r = requests.get("https://api.arcee-ai.com/health", timeout=5,
                             headers={'Authorization': f'Bearer {self.api_key}'})
            return r.status_code == 200
        except Exception:
            return False
