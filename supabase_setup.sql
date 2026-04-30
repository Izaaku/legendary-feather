-- ══════════════════════════════════════════════════════
-- LEGENDARY FEATHER — Supabase Tables Setup
-- Run this in Supabase SQL Editor
-- ══════════════════════════════════════════════════════

-- 1. Chat Conversations
CREATE TABLE chat_conversations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_email TEXT,
    user_name TEXT,
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'assigned', 'resolved', 'closed')),
    assigned_agent TEXT,
    subject TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- 2. Chat Messages
CREATE TABLE chat_messages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    conversation_id UUID REFERENCES chat_conversations(id) ON DELETE CASCADE,
    sender_id TEXT NOT NULL,
    sender_type TEXT NOT NULL CHECK (sender_type IN ('customer', 'agent', 'system')),
    sender_name TEXT,
    message TEXT NOT NULL,
    read BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Response Templates (Bank)
CREATE TABLE response_templates (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    keywords TEXT[] DEFAULT '{}',
    category TEXT DEFAULT 'general',
    usage_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 4. FAQ Entries
CREATE TABLE faq_entries (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    category TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    is_published BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 5. Call Logs (Traceability / Security)
CREATE TABLE call_logs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_email TEXT,
    digital_fingerprint TEXT NOT NULL,
    session_type TEXT CHECK (session_type IN ('conference', 'face_to_face', 'text')),
    voice_profile_used TEXT,
    source_lang TEXT,
    target_lang TEXT,
    duration_seconds INTEGER,
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ── Indexes for performance ──────────────────────────
CREATE INDEX idx_chat_conv_user ON chat_conversations(user_id);
CREATE INDEX idx_chat_conv_status ON chat_conversations(status);
CREATE INDEX idx_chat_msg_conv ON chat_messages(conversation_id);
CREATE INDEX idx_chat_msg_created ON chat_messages(created_at);
CREATE INDEX idx_call_logs_fingerprint ON call_logs(digital_fingerprint);
CREATE INDEX idx_call_logs_user ON call_logs(user_id);
CREATE INDEX idx_faq_category ON faq_entries(category);

-- ── Row Level Security ───────────────────────────────
ALTER TABLE chat_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE response_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE faq_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_logs ENABLE ROW LEVEL SECURITY;

-- Allow all operations via service role (our backend)
-- The anon key will only read FAQ entries (public)
CREATE POLICY "Service role full access" ON chat_conversations FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON chat_messages FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON response_templates FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Public read FAQ" ON faq_entries FOR SELECT USING (is_published = true);
CREATE POLICY "Service role full access FAQ" ON faq_entries FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON call_logs FOR ALL USING (true) WITH CHECK (true);

-- ── Insert sample FAQ entries ────────────────────────
INSERT INTO faq_entries (category, question, answer, sort_order) VALUES
-- Getting Started
('Getting Started', 'What is Legendary Feather?', 'Legendary Feather is a real-time AI translation platform that lets you communicate across languages instantly. It supports voice translation, text translation, and image translation with voice cloning capabilities.', 1),
('Getting Started', 'How do I start a translation session?', 'Log in to your account, select your source and target languages, choose your mode (Conference or Face-to-Face), and click Start Translation. The system will begin listening and translating in real-time.', 2),
('Getting Started', 'What languages are supported?', 'We support 16+ languages including English, Spanish, French, German, Italian, Portuguese, Chinese, Japanese, Korean, Arabic, Russian, Turkish, Polish, Dutch, Czech, and Hungarian.', 3),
('Getting Started', 'Do I need to install anything?', 'No installation required. Legendary Feather works directly in your web browser. We recommend Chrome or Edge for the best experience.', 4),

-- Translation Features
('Translation Features', 'What is Conference Mode?', 'Conference Mode uses cloud-based speech recognition to transcribe and translate audio in real-time. It records in 5-second cycles and sends audio to our servers for processing.', 5),
('Translation Features', 'What is Face-to-Face Mode?', 'Face-to-Face Mode is designed for in-person conversations. It uses premium voice synthesis to produce natural-sounding translations, ideal for meetings and personal interactions.', 6),
('Translation Features', 'How does Image Translation work?', 'Take a photo or upload an image containing text. Our AI vision system reads all visible text (signs, menus, documents) and translates it to your target language.', 7),
('Translation Features', 'How accurate are the translations?', 'We use DeepL, one of the world''s most accurate translation engines, combined with OpenAI for speech recognition. Accuracy is typically 95%+ for supported language pairs.', 8),

-- Voice Cloning
('Voice Cloning', 'What is Voice Cloning?', 'Voice Cloning lets you create a digital copy of your voice. When translations are spoken back, they sound like you instead of a generic AI voice.', 9),
('Voice Cloning', 'Is Voice Cloning safe?', 'Yes. Every cloned voice is registered to your account with a digital fingerprint. All generated audio contains an invisible watermark linking it to the creator. Misuse results in immediate account termination.', 10),
('Voice Cloning', 'How do I register my voice?', 'Go to the Voice Registration section, read the displayed phrase aloud for 10-30 seconds, and save your profile. You must accept the Ethical Use Agreement before registering.', 11),
('Voice Cloning', 'Can I clone someone else''s voice?', 'Only with their explicit written consent. Cloning a voice without authorization is strictly prohibited and may result in legal action. See our Ethical Use Agreement.', 12),

-- Plans & Pricing
('Plans & Pricing', 'What plans are available?', 'We offer three plans: Personal (€9.99/month, 120 minutes), Premium (€24.99/month, 600 minutes with voice cloning), and Business (€89.99/month, unlimited minutes with full features).', 13),
('Plans & Pricing', 'Can I change my plan?', 'Yes, you can upgrade or downgrade your plan at any time from your Dashboard. Changes take effect at the start of your next billing cycle.', 14),
('Plans & Pricing', 'What happens when I run out of minutes?', 'You will receive a notification when you reach 80% of your monthly minutes. Once depleted, you can upgrade your plan or wait for the next billing cycle to reset.', 15),
('Plans & Pricing', 'Is there a free trial?', 'New users receive a limited trial to test the platform. Contact our support team for details on current trial offers.', 16),

-- Billing & Payments
('Billing & Payments', 'What payment methods do you accept?', 'We accept all major credit and debit cards (Visa, Mastercard, American Express) processed securely through Stripe.', 17),
('Billing & Payments', 'How do I cancel my subscription?', 'Go to Dashboard → Account Settings → Subscription and click Cancel. You will retain access until the end of your current billing period.', 18),
('Billing & Payments', 'Will I get a refund if I cancel?', 'We offer a 7-day money-back guarantee for new subscriptions. After that period, cancellations take effect at the end of the current billing cycle without a refund for the remaining period.', 19),

-- Account & Security
('Account & Security', 'How is my data protected?', 'All communications are encrypted. We use JWT authentication, HMAC-SHA256 signed tokens, and Content Security Policy headers. Audio is processed in real-time and not stored permanently.', 20),
('Account & Security', 'What is a Digital Fingerprint?', 'Every translation session generates a unique 12-character code linked to your account. This ensures full traceability and prevents misuse of the platform.', 21),
('Account & Security', 'I forgot my password. How do I reset it?', 'Click "Forgot Password" on the login page and enter your email. You will receive a reset link within minutes.', 22),
('Account & Security', 'Can I use Legendary Feather on multiple devices?', 'Yes, your account works on any device with a modern web browser. Sessions are tied to your account, not your device.', 23),

-- Technical Issues
('Technical Issues', 'The microphone is not working. What should I do?', 'Make sure your browser has permission to access the microphone. Check Settings → Privacy → Microphone. Also try using Chrome or Edge for best compatibility.', 24),
('Technical Issues', 'Audio quality is poor. How can I improve it?', 'Use a headset or external microphone for best results. Ensure you are in a quiet environment and your internet connection is stable (minimum 5 Mbps recommended).', 25),
('Technical Issues', 'The translation seems delayed. Is this normal?', 'A slight delay (1-3 seconds) is normal as audio is processed through our cloud services. If delays exceed 5 seconds, check your internet connection.', 26),
('Technical Issues', 'Which browsers are supported?', 'We recommend Google Chrome or Microsoft Edge for the best experience. Safari and Firefox are supported but may have limited microphone functionality.', 27);

-- ── Insert sample response templates ─────────────────
INSERT INTO response_templates (title, body, keywords, category) VALUES
('Welcome greeting', 'Hi there! Welcome to Legendary Feather support. How can I help you today?', ARRAY['hello', 'hi', 'hey', 'start', 'new'], 'greeting'),
('Subscription help', 'I''d be happy to help with your subscription. Could you tell me which plan you''re currently on (Personal, Premium, or Business) and what change you''d like to make?', ARRAY['plan', 'subscription', 'upgrade', 'downgrade', 'change plan', 'pricing'], 'billing'),
('Microphone troubleshooting', 'Let''s fix that microphone issue. Please try these steps:\n1. Click the lock icon in your browser''s address bar\n2. Make sure Microphone is set to "Allow"\n3. Refresh the page and try again\n\nIf it still doesn''t work, try using Google Chrome.', ARRAY['microphone', 'mic', 'not working', 'audio', 'permission', 'cant hear'], 'technical'),
('Voice cloning info', 'Voice cloning is available on Premium (€24.99/mo) and Business (€89.99/mo) plans. To set it up, go to the Voice Registration section in the app, accept the Ethical Use Agreement, and record a 10-30 second sample of your voice.', ARRAY['voice', 'clone', 'cloning', 'voice profile', 'register voice'], 'features'),
('Refund request', 'I understand you''d like a refund. We offer a 7-day money-back guarantee for new subscriptions. Could you please share your account email and the date you subscribed so I can look into this for you?', ARRAY['refund', 'money back', 'cancel', 'charge', 'charged'], 'billing'),
('Positive feedback response', 'Thank you so much for the kind words! We''re thrilled that you''re enjoying Legendary Feather. Your feedback means a lot to our team. Is there anything else we can help you with?', ARRAY['great', 'awesome', 'love', 'amazing', 'excellent', 'good', 'thank'], 'general'),
('Translation accuracy', 'Our translations are powered by DeepL, one of the most accurate translation engines available. If you notice any specific translation that seems off, please share the original text and the translation so we can investigate.', ARRAY['wrong translation', 'incorrect', 'accuracy', 'bad translation', 'mistranslation'], 'technical'),
('Escalation notice', 'I want to make sure this gets the attention it deserves. I''m escalating your case to our senior support team. You should hear back within 24 hours. Is there anything else I can help with in the meantime?', ARRAY['escalate', 'manager', 'supervisor', 'urgent', 'serious', 'unresolved'], 'escalation');


-- ══════════════════════════════════════════════════════
-- VOICE AUDIT & TRACEABILITY (anti-fraud / anti-extortion)
-- ══════════════════════════════════════════════════════
-- Every voice operation (registration, cloning, deletion) creates a row
-- here. Combined with the audio_hash (SHA-256 of the generated MP3) and
-- session_id, we can trace any audio back to the user that generated it
-- and the exact session it came from. Used for:
--   - Legal / law enforcement requests
--   - Account suspension on misuse reports
--   - Internal abuse investigations
-- IMPORTANT: we DO NOT store the translated text or IPs to keep this
-- minimal and privacy-friendly. Only metadata.

CREATE TABLE IF NOT EXISTS voice_audit_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT,
    voice_profile_id TEXT,
    event_type TEXT NOT NULL CHECK (event_type IN ('register', 'tts_clone', 'tts_standard', 'delete', 'consent_accepted')),
    target_language TEXT,
    source_language TEXT,
    char_count INT DEFAULT 0,
    audio_hash TEXT,                  -- SHA-256 hex of the generated audio (for replay-detection / forensic match)
    consent_timestamp TIMESTAMPTZ,    -- only set on 'register' / 'consent_accepted' events
    user_plan TEXT,                   -- snapshot of the user's plan at the time of the event
    error TEXT,                       -- if the event failed (TTS error, etc.), we still log it
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for fast queries from the admin panel
CREATE INDEX IF NOT EXISTS idx_voice_audit_user
    ON voice_audit_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_voice_audit_session
    ON voice_audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_audit_hash
    ON voice_audit_log(audio_hash);
CREATE INDEX IF NOT EXISTS idx_voice_audit_event
    ON voice_audit_log(event_type, created_at DESC);


-- Each F2F translation session generates ONE row. Each individual
-- translation in that session creates a voice_audit_log row referring back
-- via session_id. This gives us a clean parent-child relationship and lets
-- us answer "who initiated this session and what voice did they use?".

CREATE TABLE IF NOT EXISTS translation_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ,
    total_translations INT DEFAULT 0,
    total_chars INT DEFAULT 0,
    voice_profile_used TEXT,
    primary_languages TEXT,           -- e.g. "en,es" — which lang pair was active
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_translation_sessions_user
    ON translation_sessions(user_id, created_at DESC);
