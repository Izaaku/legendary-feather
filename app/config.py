"""Centralized configuration for Legendary Feather Translator."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-change-me')
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///legendary_feather.db')
    APP_URL = os.getenv('APP_URL', 'http://localhost:5000')

    # Stripe
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

    # AI Services
    OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434')
    ARCEE_API_KEY = os.getenv('ARCEE_API_KEY')

    # TTS Engine (Dual: XTTS v2 + GPT-SoVITS)
    TTS_DEFAULT_MODE = os.getenv('TTS_DEFAULT_MODE', 'conference')
    XTTS_MODEL_PATH = os.getenv('XTTS_MODEL_PATH', './models/xtts_v2')
    GPTSOVITS_MODEL_PATH = os.getenv('GPTSOVITS_MODEL_PATH', './models/gptsovits')

    # Voice Cloning
    VOICE_PROFILES_PATH = os.getenv('VOICE_PROFILES_PATH', './data/voice_profiles')

    # Performance Optimization
    USE_DEEPSPEED = os.getenv('USE_DEEPSPEED', 'false').lower() == 'true'
    USE_TENSORRT = os.getenv('USE_TENSORRT', 'false').lower() == 'true'


# Pricing tiers
PRICING = {
    'owner': {
        'name': 'Owner',
        'price': 0,
        'currency': 'eur',
        'minutes': 999999,
        'extra_rate': 0,
        'stripe_price_id': None,
        'features': [
            'Unlimited access',
            'All AI models',
            'Unlimited minutes',
            '100+ languages',
            'HD voice synthesis',
            'Conference mode (XTTS v2)',
            'Face-to-face mode (GPT-SoVITS)',
            'Voice cloning (unlimited profiles)',
            'DeepSpeed optimization',
            'TensorRT optimization',
            'Priority support',
            'API access',
            'Admin panel'
        ]
    },
    'basic': {
        'name': 'Basic',
        'price': 9.99,
        'currency': 'eur',
        'minutes': 60,
        'extra_rate': 0.15,
        'stripe_price_id': os.getenv('STRIPE_PRICE_BASIC'),
        'features': [
            'Speech-to-Text AI',
            '60 minutes/month',
            '100+ languages',
            'Standard quality',
            'Conference mode (XTTS v2)'
        ]
    },
    'premium': {
        'name': 'Premium',
        'price': 24.99,
        'currency': 'eur',
        'minutes': 200,
        'extra_rate': 0.15,
        'stripe_price_id': os.getenv('STRIPE_PRICE_PREMIUM'),
        'features': [
            'Advanced Translation AI',
            '200 minutes/month',
            '100+ languages',
            'HD voice synthesis',
            'Conference mode (XTTS v2)',
            'Face-to-face mode (GPT-SoVITS)',
            'Voice cloning (1 profile)'
        ]
    },
    'business': {
        'name': 'Business',
        'price': 89.99,
        'currency': 'eur',
        'minutes': 1000,
        'extra_rate': 0.14,
        'stripe_price_id': os.getenv('STRIPE_PRICE_BUSINESS'),
        'features': [
            'All AI models',
            '1000 minutes/month',
            '100+ languages',
            'HD voice synthesis',
            'Conference mode (XTTS v2)',
            'Face-to-face mode (GPT-SoVITS)',
            'Voice cloning (unlimited profiles)',
            'DeepSpeed optimization',
            'Priority support',
            'API access'
        ]
    }
}

# XTTS v2 natively supported languages (16 languages)
CORE_LANGUAGES = ['en', 'es', 'fr', 'de', 'it', 'pt', 'pl', 'tr', 'ru', 'nl', 'cs', 'ar', 'zh', 'ja', 'ko', 'hu']

# Supported languages (100 languages)
LANGUAGES = {
    'en': {'name': 'English', 'flag': '\U0001f1fa\U0001f1f8'},
    'es': {'name': 'Spanish', 'flag': '\U0001f1f2\U0001f1fd'},
    'fr': {'name': 'French', 'flag': '\U0001f1eb\U0001f1f7'},
    'de': {'name': 'German', 'flag': '\U0001f1e9\U0001f1ea'},
    'it': {'name': 'Italian', 'flag': '\U0001f1ee\U0001f1f9'},
    'pt': {'name': 'Portuguese', 'flag': '\U0001f1e7\U0001f1f7'},
    'ru': {'name': 'Russian', 'flag': '\U0001f1f7\U0001f1fa'},
    'zh': {'name': 'Chinese', 'flag': '\U0001f1e8\U0001f1f3'},
    'ja': {'name': 'Japanese', 'flag': '\U0001f1ef\U0001f1f5'},
    'ko': {'name': 'Korean', 'flag': '\U0001f1f0\U0001f1f7'},
    'ar': {'name': 'Arabic', 'flag': '\U0001f1f8\U0001f1e6'},
    'hi': {'name': 'Hindi', 'flag': '\U0001f1ee\U0001f1f3'},
    'fil': {'name': 'Filipino', 'flag': '\U0001f1f5\U0001f1ed'},
    'nl': {'name': 'Dutch', 'flag': '\U0001f1f3\U0001f1f1'},
    'pl': {'name': 'Polish', 'flag': '\U0001f1f5\U0001f1f1'},
    'tr': {'name': 'Turkish', 'flag': '\U0001f1f9\U0001f1f7'},
    'sv': {'name': 'Swedish', 'flag': '\U0001f1f8\U0001f1ea'},
    'da': {'name': 'Danish', 'flag': '\U0001f1e9\U0001f1f0'},
    'th': {'name': 'Thai', 'flag': '\U0001f1f9\U0001f1ed'},
    'vi': {'name': 'Vietnamese', 'flag': '\U0001f1fb\U0001f1f3'},
    'id': {'name': 'Indonesian', 'flag': '\U0001f1ee\U0001f1e9'},
    'ms': {'name': 'Malay', 'flag': '\U0001f1f2\U0001f1fe'},
    'sw': {'name': 'Swahili', 'flag': '\U0001f1f0\U0001f1ea'},
    'am': {'name': 'Amharic', 'flag': '\U0001f1ea\U0001f1f9'},
    'yo': {'name': 'Yoruba', 'flag': '\U0001f1f3\U0001f1ec'},
    'ha': {'name': 'Hausa', 'flag': '\U0001f1f3\U0001f1ea'},
    'ig': {'name': 'Igbo', 'flag': '\U0001f1f3\U0001f1ec'},
    'zu': {'name': 'Zulu', 'flag': '\U0001f1ff\U0001f1e6'},
    'af': {'name': 'Afrikaans', 'flag': '\U0001f1ff\U0001f1e6'},
    'bn': {'name': 'Bengali', 'flag': '\U0001f1e7\U0001f1e9'},
    'ta': {'name': 'Tamil', 'flag': '\U0001f1ee\U0001f1f3'},
    'te': {'name': 'Telugu', 'flag': '\U0001f1ee\U0001f1f3'},
    'ml': {'name': 'Malayalam', 'flag': '\U0001f1ee\U0001f1f3'},
    'kn': {'name': 'Kannada', 'flag': '\U0001f1ee\U0001f1f3'},
    'gu': {'name': 'Gujarati', 'flag': '\U0001f1ee\U0001f1f3'},
    'mr': {'name': 'Marathi', 'flag': '\U0001f1ee\U0001f1f3'},
    'pa': {'name': 'Punjabi', 'flag': '\U0001f1ee\U0001f1f3'},
    'ur': {'name': 'Urdu', 'flag': '\U0001f1f5\U0001f1f0'},
    'fa': {'name': 'Persian', 'flag': '\U0001f1ee\U0001f1f7'},
    'he': {'name': 'Hebrew', 'flag': '\U0001f1ee\U0001f1f1'},
    'el': {'name': 'Greek', 'flag': '\U0001f1ec\U0001f1f7'},
    'cs': {'name': 'Czech', 'flag': '\U0001f1e8\U0001f1ff'},
    'sk': {'name': 'Slovak', 'flag': '\U0001f1f8\U0001f1f0'},
    'hu': {'name': 'Hungarian', 'flag': '\U0001f1ed\U0001f1fa'},
    'ro': {'name': 'Romanian', 'flag': '\U0001f1f7\U0001f1f4'},
    'bg': {'name': 'Bulgarian', 'flag': '\U0001f1e7\U0001f1ec'},
    'hr': {'name': 'Croatian', 'flag': '\U0001f1ed\U0001f1f7'},
    'sr': {'name': 'Serbian', 'flag': '\U0001f1f7\U0001f1f8'},
    'sl': {'name': 'Slovenian', 'flag': '\U0001f1f8\U0001f1ee'},
    'uk': {'name': 'Ukrainian', 'flag': '\U0001f1fa\U0001f1e6'},
    'lt': {'name': 'Lithuanian', 'flag': '\U0001f1f1\U0001f1f9'},
    'lv': {'name': 'Latvian', 'flag': '\U0001f1f1\U0001f1fb'},
    'et': {'name': 'Estonian', 'flag': '\U0001f1ea\U0001f1ea'},
    'ka': {'name': 'Georgian', 'flag': '\U0001f1ec\U0001f1ea'},
    'hy': {'name': 'Armenian', 'flag': '\U0001f1e6\U0001f1f2'},
    'az': {'name': 'Azerbaijani', 'flag': '\U0001f1e6\U0001f1ff'},
    'kk': {'name': 'Kazakh', 'flag': '\U0001f1f0\U0001f1ff'},
    'uz': {'name': 'Uzbek', 'flag': '\U0001f1fa\U0001f1ff'},
    'mn': {'name': 'Mongolian', 'flag': '\U0001f1f2\U0001f1f3'},
    'my': {'name': 'Burmese', 'flag': '\U0001f1f2\U0001f1f2'},
    'km': {'name': 'Khmer', 'flag': '\U0001f1f0\U0001f1ed'},
    'lo': {'name': 'Lao', 'flag': '\U0001f1f1\U0001f1e6'},
    'si': {'name': 'Sinhala', 'flag': '\U0001f1f1\U0001f1f0'},
    'ne': {'name': 'Nepali', 'flag': '\U0001f1f3\U0001f1f5'},
    'no': {'name': 'Norwegian', 'flag': '\U0001f1f3\U0001f1f4'},
    'fi': {'name': 'Finnish', 'flag': '\U0001f1eb\U0001f1ee'},
    'is': {'name': 'Icelandic', 'flag': '\U0001f1ee\U0001f1f8'},
    'ga': {'name': 'Irish', 'flag': '\U0001f1ee\U0001f1ea'},
    'cy': {'name': 'Welsh', 'flag': '\U0001f1ec\U0001f1e7'},
    'eu': {'name': 'Basque', 'flag': '\U0001f1ea\U0001f1f8'},
    'ca': {'name': 'Catalan', 'flag': '\U0001f1ea\U0001f1f8'},
    'gl': {'name': 'Galician', 'flag': '\U0001f1ea\U0001f1f8'},
    'mt': {'name': 'Maltese', 'flag': '\U0001f1f2\U0001f1f9'},
    'sq': {'name': 'Albanian', 'flag': '\U0001f1e6\U0001f1f1'},
    'mk': {'name': 'Macedonian', 'flag': '\U0001f1f2\U0001f1f0'},
    'bs': {'name': 'Bosnian', 'flag': '\U0001f1e7\U0001f1e6'},
    'be': {'name': 'Belarusian', 'flag': '\U0001f1e7\U0001f1fe'},
    'tl': {'name': 'Tagalog', 'flag': '\U0001f1f5\U0001f1ed'},
    'jv': {'name': 'Javanese', 'flag': '\U0001f1ee\U0001f1e9'},
    'su': {'name': 'Sundanese', 'flag': '\U0001f1ee\U0001f1e9'},
    'ceb': {'name': 'Cebuano', 'flag': '\U0001f1f5\U0001f1ed'},
    'mi': {'name': 'Maori', 'flag': '\U0001f1f3\U0001f1ff'},
    'sm': {'name': 'Samoan', 'flag': '\U0001f1fc\U0001f1f8'},
    'to': {'name': 'Tongan', 'flag': '\U0001f1f9\U0001f1f4'},
    'fj': {'name': 'Fijian', 'flag': '\U0001f1eb\U0001f1ef'},
    'haw': {'name': 'Hawaiian', 'flag': '\U0001f1fa\U0001f1f8'},
    'so': {'name': 'Somali', 'flag': '\U0001f1f8\U0001f1f4'},
    'ti': {'name': 'Tigrinya', 'flag': '\U0001f1ea\U0001f1f7'},
    'om': {'name': 'Oromo', 'flag': '\U0001f1ea\U0001f1f9'},
    'rw': {'name': 'Kinyarwanda', 'flag': '\U0001f1f7\U0001f1fc'},
    'lg': {'name': 'Luganda', 'flag': '\U0001f1fa\U0001f1ec'},
    'sn': {'name': 'Shona', 'flag': '\U0001f1ff\U0001f1fc'},
    'xh': {'name': 'Xhosa', 'flag': '\U0001f1ff\U0001f1e6'},
    'st': {'name': 'Sesotho', 'flag': '\U0001f1f1\U0001f1f8'},
    'tn': {'name': 'Tswana', 'flag': '\U0001f1e7\U0001f1fc'},
    'ps': {'name': 'Pashto', 'flag': '\U0001f1e6\U0001f1eb'},
    'ku': {'name': 'Kurdish', 'flag': '\U0001f1f2\U0001f1f6'},
    'tg': {'name': 'Tajik', 'flag': '\U0001f1f9\U0001f1ef'},
    'ky': {'name': 'Kyrgyz', 'flag': '\U0001f1f0\U0001f1ec'},
    'tk': {'name': 'Turkmen', 'flag': '\U0001f1f9\U0001f1f2'},
    'sd': {'name': 'Sindhi', 'flag': '\U0001f1f5\U0001f1f0'},
}
