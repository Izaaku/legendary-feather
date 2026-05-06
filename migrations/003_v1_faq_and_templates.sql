-- ════════════════════════════════════════════════════════════════
-- V1 FAQ + Response Templates seed
-- Run this in Supabase SQL editor (or psql) once after deploy.
-- It REPLACES all existing FAQ entries with the V1-correct copy
-- and seeds the response_templates table with empathetic canned
-- replies the support agent can insert in one click.
-- ════════════════════════════════════════════════════════════════

-- ─── 1. FAQs ───────────────────────────────────────────────
DELETE FROM faq_entries;

INSERT INTO faq_entries (category, question, answer, sort_order, is_published) VALUES

-- General
('General', 'What is Legendary Feather?',
 'Legendary Feather is a real-time AI translation platform for travelers, expats, and anyone who needs to communicate across languages in person. It supports voice translation in face-to-face mode, text translation, and image translation — all in 100+ languages with a natural, premium voice.',
 1, true),

('General', 'How do I use it?',
 'Sign in to your account, choose Language 1 and Language 2 (the two languages of the conversation), and press the talk button. Your voice is transcribed, translated, and read aloud in the other language in about 2 seconds. Both people share the same phone, taking turns to speak.',
 2, true),

('General', 'Do I need to install anything?',
 'No. Legendary Feather works directly in your web browser — no app store download required. On mobile (iOS or Android) you can also "Add to Home Screen" from your browser to get an app-like icon. We recommend Chrome, Safari, or Edge for the best experience.',
 3, true),

-- Languages
('Languages', 'What languages are supported?',
 'We support 100+ languages with full voice output. Click any language below to start a translation with it preselected: <a href="/app?lang=en">English</a>, <a href="/app?lang=es">Spanish</a>, <a href="/app?lang=fr">French</a>, <a href="/app?lang=de">German</a>, <a href="/app?lang=it">Italian</a>, <a href="/app?lang=pt">Portuguese</a>, <a href="/app?lang=nl">Dutch</a>, <a href="/app?lang=pl">Polish</a>, <a href="/app?lang=ru">Russian</a>, <a href="/app?lang=zh">Chinese</a>, <a href="/app?lang=ja">Japanese</a>, <a href="/app?lang=ko">Korean</a>, <a href="/app?lang=ar">Arabic</a>, <a href="/app?lang=hi">Hindi</a>, <a href="/app?lang=tr">Turkish</a>, <a href="/app?lang=sv">Swedish</a>, <a href="/app?lang=th">Thai</a>, <a href="/app?lang=vi">Vietnamese</a>, <a href="/app?lang=id">Indonesian</a>, <a href="/app?lang=tl">Tagalog</a>, plus 80+ more available in the language selector inside the app.',
 1, true),

('Languages', 'Which languages have the best quality?',
 'All 100+ languages are supported, but the 16 core languages have the most natural voice output: English, Spanish, French, German, Italian, Portuguese, Dutch, Polish, Russian, Turkish, Czech, Hungarian, Chinese, Japanese, Korean, and Arabic.',
 2, true),

-- Plans & Billing
('Plans & Billing', 'What plans are available?',
 'Free (5 min/month, no credit card), Travel Pass (€9.99 once for 100 minutes valid 7 days, perfect for trips), Tourist (€4.99/mo for 60 minutes — for frequent travelers), and Tourist Pro (€14.99/mo for 150 standard + 30 premium minutes, with regional dialects and priority support). You can also pay-as-you-go: 40 minutes for €10, valid 1 year.',
 1, true),

('Plans & Billing', 'Will I get a refund if I cancel?',
 'Travel Pass: it''s a one-time purchase, so it isn''t refundable once activated, but it simply expires after 7 days — no recurring charge. Monthly subscriptions: cancel any time, you keep access until the end of the billing period, no refund for unused days. If something went wrong on our side (the service was down, the translation failed repeatedly), contact support and we''ll make it right — that''s on us, not on you.',
 2, true),

('Plans & Billing', 'What happens when I run out of minutes?',
 'Translation pauses with a friendly message and you can either upgrade your plan or buy a top-up pack. Your account is never charged extra without your consent — we don''t do surprise overages.',
 3, true),

('Plans & Billing', 'Can I change my plan later?',
 'Yes, anytime from your account dashboard. Upgrades take effect immediately and we prorate the difference. Downgrades take effect at the next billing cycle.',
 4, true),

-- Quality & Privacy
('Quality & Privacy', 'How accurate are the translations?',
 'For the major language pairs (English ↔ Spanish, French, German, Portuguese, Italian, Chinese, Japanese, etc.) accuracy is consistently above 95%. For less common languages it''s typically 85-95% — good enough for everyday conversation, but proper names and idioms can sometimes get lost. We''re always improving.',
 1, true),

('Quality & Privacy', 'Is my voice or audio stored?',
 'Audio is processed in real-time and is not stored after the translation is complete. We keep a short text record of your translations for billing and history purposes only — you can clear it from your account at any time.',
 2, true),

('Quality & Privacy', 'Who can see my conversations?',
 'Only you. Translations are end-to-end through encrypted connections (HTTPS + WSS). We don''t share your conversation content with third parties or use it to train AI models.',
 3, true);


-- ─── 2. Response templates ─────────────────────────────────
DELETE FROM response_templates;

INSERT INTO response_templates (title, body, keywords, category, is_active) VALUES

('Greeting',
 'Hi {customer_name}, this is {agent_name} from Legendary Feather. How can I help you today?',
 ARRAY['hello','hi','hey','start'],
 'greeting', true),

('Experience check-in',
 'Hi {customer_name}, this is {agent_name}. Quick check — how has your experience with our service been so far? Anything we can improve for you?',
 ARRAY['feedback','experience','check-in'],
 'greeting', true),

('Refund — Travel Pass',
 'Hi {customer_name}, the Travel Pass is a one-time 7-day purchase so it doesn''t renew on its own — once activated it isn''t refundable, but it expires automatically with no further charges. Was there a specific issue with the service we can fix for you?',
 ARRAY['refund','travel pass','cancel'],
 'billing', true),

('Refund — Monthly subscription',
 'Hi {customer_name}, you can cancel your monthly plan from your dashboard at any time. You''ll keep access until the end of the current billing period, with no charge after that. We don''t prorate refunds for unused days unless the service had an outage on our side — let me know if you''ve experienced any issues and I''ll look into it.',
 ARRAY['refund','monthly','cancel','subscription'],
 'billing', true),

('Out of minutes',
 'Hi {customer_name}, looks like you''ve used your monthly minutes. You can either upgrade your plan or grab a pay-as-you-go top-up (40 min for €10, valid 1 year). Want me to send you the upgrade link?',
 ARRAY['out of minutes','no minutes','upgrade'],
 'usage', true),

('Translation issue',
 'Hi {customer_name}, sorry the translation didn''t come out right. Can you tell me which two languages you were using and what the original phrase was? I''ll check the logs and either credit you the minutes or escalate it to engineering.',
 ARRAY['translation','wrong','accuracy','error'],
 'support', true),

('Audio not working',
 'Hi {customer_name}, audio issues are usually fixable in 2 minutes — could you check (1) that your phone''s mute switch is off, (2) that you''ve granted microphone permission to your browser, and (3) try refreshing the page? If those don''t help, let me know and we''ll dig deeper.',
 ARRAY['audio','no sound','microphone','speaker'],
 'support', true),

('Closing — resolved',
 'Hi {customer_name}, glad we could sort that out. Is there anything else I can help with? Otherwise, I''ll mark this as resolved. Have a great day!',
 ARRAY['close','resolve','done','thanks'],
 'closing', true);
