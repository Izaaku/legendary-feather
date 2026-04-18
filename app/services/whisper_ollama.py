"""Speech-to-Text service using Whisper via Ollama."""
import requests
import base64
import os


class WhisperOllama:
    def __init__(self, base_url=None):
        self.base_url = base_url or os.getenv('OLLAMA_URL', 'http://localhost:11434')

    def transcribe(self, audio_bytes, language='en'):
        """
        Transcribe audio to text using Whisper through Ollama.

        Args:
            audio_bytes: Raw audio bytes (WAV format preferred)
            language: Language code for transcription

        Returns:
            dict with 'text', 'confidence', 'detected_lang', 'words'
        """
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

        payload = {
            "model": "whisper-large-v3",
            "inputs": [{
                "audio": audio_b64,
                "response_format": {
                    "type": "segments",
                    "language": language
                }
            }]
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()

            transcript = ""
            words = []

            resp = result.get('response', {})
            if resp and resp.get('segments'):
                for segment in resp['segments']:
                    transcript += segment.get('text', '') + " "
                    for word in segment.get('words', []):
                        words.append({
                            'word': word.get('word', ''),
                            'start': word.get('start_time', 0),
                            'end': word.get('end_time', 0),
                        })

            return {
                'text': transcript.strip(),
                'confidence': resp.get('confidence', 0),
                'detected_lang': language,
                'words': words
            }

        except requests.exceptions.Timeout:
            print("[Whisper] Request timed out")
            return self._empty_result(language)
        except requests.exceptions.ConnectionError:
            print("[Whisper] Cannot connect to Ollama")
            return self._empty_result(language)
        except Exception as e:
            print(f"[Whisper] Error: {e}")
            return self._empty_result(language)

    def _empty_result(self, language):
        return {
            'text': '',
            'confidence': 0,
            'detected_lang': language,
            'words': []
        }

    def health_check(self):
        """Check if Ollama/Whisper service is available."""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False
