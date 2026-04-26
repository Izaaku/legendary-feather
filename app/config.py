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

    # TTS Engine modes (deprecated 'conference' removed from UI; backend still tolerates it)
    # Active modes: 'face_to_face' (tourist) and 'pro' (Virtual Audio Driver)
    TTS_DEFAULT_MODE = os.getenv('TTS_DEFAULT_MODE', 'face_to_face')
    XTTS_MODEL_PATH = os.getenv('XTTS_MODEL_PATH', './models/xtts_v2')
    GPTSOVITS_MODEL_PATH = os.getenv('GPTSOVITS_MODEL_PATH', './models/gptsovits')

    # Voice Cloning
    VOICE_PROFILES_PATH = os.getenv('VOICE_PROFILES_PATH', './data/voice_profiles')

    # Performance Optimization
    USE_DEEPSPEED = os.getenv('USE_DEEPSPEED', 'false').lower() == 'true'
    USE_TENSORRT = os.getenv('USE_TENSORRT', 'false').lower() == 'true'

    # Sales / Leads notification email (Enterprise inquiries)
    SALES_NOTIFY_EMAIL = os.getenv('SALES_NOTIFY_EMAIL', 'sales@legendaryfeather.com')


# ============================================================================
# PRICING TIERS — Multi-currency (EUR for travelers, USD for business)
#
# Each plan defines:
#   category:           'traveler' | 'business' | 'payg' | 'internal'
#   billing:            'free' | 'monthly' | 'one_time' | 'usage' | 'custom'
#   prices:             {'eur': X, 'usd': Y}  — None means "Custom / Talk to Sales"
#   minutes_openai:     standard-quality TTS minutes/month (-1 = unlimited)
#   minutes_elevenlabs: premium-quality TTS minutes/month (caps protect margin)
#   per_seat:           True for business plans charged per agent
#   min_seats:          minimum number of seats for business plans
#   stripe_price_id_*:  Stripe Price IDs per currency (set via env vars)
# ============================================================================
PRICING = {
    # ─────────── INTERNAL ───────────
    'owner': {
        'category': 'internal',
        'name': 'Owner',
        'tagline': 'Internal use',
        'prices': {'eur': 0, 'usd': 0},
        'billing': 'free',
        'minutes_openai': -1,
        'minutes_elevenlabs': -1,
        'voice_cloning_profiles': -1,
        'languages': 100,
        'per_seat': False,
        'visible': False,
        'stripe_price_id_eur': None,
        'stripe_price_id_usd': None,
        'features': [
            'Unlimited everything',
            'All AI models',
            '100+ languages',
            'Voice cloning unlimited',
            'Admin panel',
            'API access',
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # TRAVELERS  —  B2C, EUR principal
    # Use case: tourists, expats, hospitality workers, students abroad
    # ═══════════════════════════════════════════════════════════════════════
    'free': {
        'category': 'traveler',
        'name': 'Free',
        'tagline': 'Try before you buy',
        'prices': {'eur': 0, 'usd': 0},
        'billing': 'free',
        'minutes_openai': 5,
        'minutes_elevenlabs': 0,
        'voice_cloning_profiles': 0,
        'languages': 100,
        'per_seat': False,
        'visible': True,
        'stripe_price_id_eur': None,
        'stripe_price_id_usd': None,
        'features': [
            '5 minutes / month',
            '100+ languages',
            'Standard voice (OpenAI TTS)',
            'Mobile PWA',
            'No credit card required',
        ],
    },
    'travel_pass': {
        'category': 'traveler',
        'name': 'Travel Pass',
        'tagline': 'Perfect for your trip',
        'prices': {'eur': 9.99, 'usd': 10.99},
        'billing': 'one_time',
        'duration_days': 7,
        'minutes_openai': 100,
        'minutes_elevenlabs': 0,
        'voice_cloning_profiles': 0,
        'languages': 100,
        'per_seat': False,
        'visible': True,
        'highlight': True,  # most popular for travelers
        'stripe_price_id_eur': os.getenv('STRIPE_PRICE_TRAVEL_PASS_EUR'),
        'stripe_price_id_usd': os.getenv('STRIPE_PRICE_TRAVEL_PASS_USD'),
        'features': [
            '100 minutes for 7 days',
            '100+ languages',
            'Natural voice (OpenAI TTS)',
            'Face-to-face mode',
            'Mobile PWA',
            'No subscription — buy once',
        ],
    },
    'tourist': {
        'category': 'traveler',
        'name': 'Tourist',
        'tagline': 'For frequent travelers and expats',
        'prices': {'eur': 4.99, 'usd': 5.99},
        'billing': 'monthly',
        'minutes_openai': 60,
        'minutes_elevenlabs': 0,
        'voice_cloning_profiles': 0,
        'languages': 100,
        'per_seat': False,
        'visible': True,
        'stripe_price_id_eur': os.getenv('STRIPE_PRICE_TOURIST_EUR'),
        'stripe_price_id_usd': os.getenv('STRIPE_PRICE_TOURIST_USD'),
        'features': [
            '60 minutes / month',
            '100+ languages',
            'Natural voice (OpenAI TTS)',
            'Face-to-face mode',
            'Mobile PWA',
            'For expats and frequent travelers',
        ],
    },
    'tourist_pro': {
        'category': 'traveler',
        'name': 'Tourist Pro',
        'tagline': 'Premium voice + voice cloning',
        'prices': {'eur': 14.99, 'usd': 16.99},
        'billing': 'monthly',
        'minutes_openai': 150,
        'minutes_elevenlabs': 30,
        'voice_cloning_profiles': 1,
        'languages': 100,
        'per_seat': False,
        'visible': True,
        'stripe_price_id_eur': os.getenv('STRIPE_PRICE_TOURIST_PRO_EUR'),
        'stripe_price_id_usd': os.getenv('STRIPE_PRICE_TOURIST_PRO_USD'),
        'features': [
            '150 standard min + 30 premium min / month',
            '100+ languages with regional dialects',
            'Premium voice (ElevenLabs) for key conversations',
            'Voice cloning (1 profile)',
            'Offline mode (basic)',
            'Priority support',
            'For digital nomads and long-stay expats',
        ],
    },
    'payg': {
        'category': 'payg',
        'name': 'Pay-as-you-go',
        'tagline': 'For occasional use',
        'prices': {'eur': 0.25, 'usd': 0.27},  # per minute
        'billing': 'usage',
        'minutes_openai': 0,  # variable, bought via credit packs
        'minutes_elevenlabs': 0,
        'voice_cloning_profiles': 0,
        'languages': 100,
        'per_seat': False,
        'visible': True,
        'credit_packs': [
            {'eur': 10, 'usd': 11, 'minutes': 40},
            {'eur': 25, 'usd': 27, 'minutes': 110},
            {'eur': 50, 'usd': 55, 'minutes': 230},
        ],
        'stripe_price_id_eur': os.getenv('STRIPE_PRICE_PAYG_EUR'),
        'stripe_price_id_usd': os.getenv('STRIPE_PRICE_PAYG_USD'),
        'features': [
            '€0.25 / $0.27 per minute',
            'Buy credits in packs (€10 = 40 min)',
            'Credits valid for 1 year',
            'No monthly subscription',
            'Perfect for "I need it once" moments',
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # BUSINESS / PROFESSIONALS  —  B2B, USD principal
    # Use case: call centers (BPO), e-commerce sellers, recruiters,
    # international sales, telemedicine, remote support, real estate
    # ═══════════════════════════════════════════════════════════════════════
    'solo': {
        'category': 'business',
        'name': 'Solo',
        'tagline': 'Freelancers & individual sellers',
        'prices': {'usd': 29, 'eur': 26.99},
        'billing': 'monthly',
        'per_seat': False,
        'min_seats': 1,
        'minutes_openai': 600,
        'minutes_elevenlabs': 0,
        'voice_cloning_profiles': 3,
        'languages': 16,
        'visible': True,
        'stripe_price_id_usd': os.getenv('STRIPE_PRICE_SOLO_USD'),
        'stripe_price_id_eur': os.getenv('STRIPE_PRICE_SOLO_EUR'),
        'features': [
            '600 minutes / month',
            'Virtual Audio Driver (Windows / Mac)',
            'Works with Zoom, Teams, Twilio Flex, RingCentral, Five9',
            'Voice cloning (3 profiles)',
            '16 core languages',
            'Email support',
            'For freelancers, solo sellers, recruiters',
        ],
    },
    'team': {
        'category': 'business',
        'name': 'Team',
        'tagline': 'Small teams & e-commerce sellers',
        'prices': {'usd': 89, 'eur': 79.99},
        'billing': 'monthly',
        'per_seat': True,
        'min_seats': 3,
        'minutes_openai': 1500,  # per seat / month
        'minutes_elevenlabs': 50,  # per seat / month
        'voice_cloning_profiles': -1,
        'languages': 30,
        'visible': True,
        'highlight': True,  # most popular for business
        'stripe_price_id_usd': os.getenv('STRIPE_PRICE_TEAM_USD'),
        'stripe_price_id_eur': os.getenv('STRIPE_PRICE_TEAM_EUR'),
        'features': [
            '1,500 standard min + 50 premium min per agent',
            'Virtual Audio Driver (Windows / Mac)',
            'Admin dashboard with team metrics',
            'Sub-accounts for supervisors',
            'Voice cloning unlimited',
            '30+ languages',
            'API access (basic)',
            'Priority support',
            'For Mercado Libre / Amazon sellers, recruiters, remote teams',
        ],
    },
    'scale': {
        'category': 'business',
        'name': 'Scale',
        'tagline': 'Mid-size BPOs & contact centers',
        'prices': {'usd': 249, 'eur': 224.99},
        'billing': 'monthly',
        'per_seat': True,
        'min_seats': 10,
        'minutes_openai': 6000,  # per seat / month
        'minutes_elevenlabs': 200,  # per seat / month
        'voice_cloning_profiles': -1,
        'languages': 50,
        'visible': True,
        'stripe_price_id_usd': os.getenv('STRIPE_PRICE_SCALE_USD'),
        'stripe_price_id_eur': os.getenv('STRIPE_PRICE_SCALE_EUR'),
        'features': [
            '6,000 standard min + 200 premium min per agent',
            'Voice cloning of agent (premium quality)',
            'Advanced dashboard with per-agent analytics',
            'Recording + transcripts (compliance-ready)',
            'Full REST API + webhooks',
            'SSO (Google / Microsoft / Okta)',
            '50+ languages with regional dialects (Filipino-EN, Hindi-EN, MX vs ES Spanish)',
            'Dedicated account manager',
            'SLA 99.9% uptime',
            'For BPOs, call centers, large international sellers',
        ],
    },
    'enterprise': {
        'category': 'business',
        'name': 'Enterprise',
        'tagline': 'Custom for 50+ agents',
        'prices': {'usd': None, 'eur': None},  # Talk to Sales
        'billing': 'custom',
        'per_seat': True,
        'min_seats': 50,
        'minutes_openai': -1,
        'minutes_elevenlabs': -1,
        'voice_cloning_profiles': -1,
        'languages': 100,
        'visible': True,
        'stripe_price_id_usd': None,
        'stripe_price_id_eur': None,
        'features': [
            'Custom pricing for 50+ agents',
            'Dedicated deployment (your cloud or isolated Railway)',
            'SOC 2 / HIPAA / PCI compliance',
            'Custom voice models trained on your audio',
            'Custom integration with your PBX (Twilio Flex, Five9, Genesys)',
            '24/7 phone support',
            'SLA penalties in contract',
            'Annual contracts with volume discount',
            'For Fortune 500, healthcare, finance, large BPOs',
        ],
    },
}


def get_traveler_plans():
    """Return ordered list of plans visible in the Travelers section."""
    order = ['free', 'travel_pass', 'tourist', 'tourist_pro', 'payg']
    return [{'id': pid, **PRICING[pid]} for pid in order if pid in PRICING and PRICING[pid].get('visible')]


def get_business_plans():
    """Return ordered list of plans visible in the Business section."""
    order = ['solo', 'team', 'scale', 'enterprise']
    return [{'id': pid, **PRICING[pid]} for pid in order if pid in PRICING and PRICING[pid].get('visible')]


def get_plan_price(plan_id, currency='eur'):
    """Get price for a plan in the requested currency. Returns None for custom plans."""
    plan = PRICING.get(plan_id)
    if not plan:
        return None
    return plan.get('prices', {}).get(currency)


def get_stripe_price_id(plan_id, currency='eur'):
    """Get the Stripe Price ID for a plan in the requested currency."""
    plan = PRICING.get(plan_id)
    if not plan:
        return None
    key = f'stripe_price_id_{currency}'
    return plan.get(key)


# ─── Backward-compatibility shims ───────────────────────────────────────────
# Legacy code referenced `plan['minutes']`, `plan['price']`, `plan['currency']`,
# `plan['extra_rate']`. Inject those keys into every plan so existing routes
# (auth.py, payments.py, utils/pricing.py) keep working until we migrate them.
def _inject_legacy_keys(plans):
    for plan_id, plan in list(plans.items()):
        # Skip plans that already have the legacy fields
        if 'minutes' not in plan:
            mins = plan.get('minutes_openai', 0)
            plan['minutes'] = 999_999 if mins == -1 else mins
        if 'price' not in plan:
            # Pick EUR if available, else USD, else 0
            prices = plan.get('prices', {})
            plan['price'] = prices.get('eur') or prices.get('usd') or 0
        if 'currency' not in plan:
            prices = plan.get('prices', {})
            plan['currency'] = 'eur' if prices.get('eur') is not None else 'usd'
        if 'extra_rate' not in plan:
            plan['extra_rate'] = 0.15  # default overage rate (legacy default)
        if 'stripe_price_id' not in plan:
            plan['stripe_price_id'] = (plan.get('stripe_price_id_eur')
                                        or plan.get('stripe_price_id_usd'))


_inject_legacy_keys(PRICING)

# Legacy plan-name aliases — map old slugs to closest new equivalents so any
# code path still asking for 'basic' / 'premium' / 'business' resolves cleanly.
PRICING['basic'] = {**PRICING['tourist'], '_legacy_alias': 'tourist'}
PRICING['premium'] = {**PRICING['tourist_pro'], '_legacy_alias': 'tourist_pro'}
PRICING['business'] = {**PRICING['team'], '_legacy_alias': 'team'}


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
