-- Migration 007 — Polyglot Talk tables
-- Created: 2026-05-18
-- Adds 4 tables for Polyglot Talk (video/audio call rooms + transcripts + contacts).
-- Additive only — does not alter existing tables.
--
-- Run via Supabase SQL Editor (or psql):
--   psql $DATABASE_URL < migrations/007_polyglot_talk_tables.sql

-- ──────────────────────────────────────────────────────────────────────
-- 1. talk_rooms — one row per Talk call session
-- ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS talk_rooms (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    host_user_id    uuid REFERENCES users(id) ON DELETE SET NULL,
    livekit_room    text NOT NULL UNIQUE,
    status          text NOT NULL DEFAULT 'waiting'
                    CHECK (status IN ('waiting', 'active', 'ended')),
    started_at      timestamptz,
    ended_at        timestamptz,
    duration_secs   integer,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS talk_rooms_host_idx        ON talk_rooms (host_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS talk_rooms_status_idx      ON talk_rooms (status) WHERE status != 'ended';
CREATE INDEX IF NOT EXISTS talk_rooms_livekit_idx     ON talk_rooms (livekit_room);

-- ──────────────────────────────────────────────────────────────────────
-- 2. talk_participants — one row per person in a room
-- ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS talk_participants (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id         uuid NOT NULL REFERENCES talk_rooms(id) ON DELETE CASCADE,
    user_id         uuid REFERENCES users(id) ON DELETE SET NULL,
    display_name    text NOT NULL,
    spoken_lang     text NOT NULL,
    reading_lang    text,
    joined_at       timestamptz NOT NULL DEFAULT now(),
    left_at         timestamptz,
    role            text NOT NULL DEFAULT 'guest'
                    CHECK (role IN ('host', 'guest', 'agent'))
);

CREATE INDEX IF NOT EXISTS talk_participants_room_idx   ON talk_participants (room_id, joined_at);
CREATE INDEX IF NOT EXISTS talk_participants_user_idx   ON talk_participants (user_id) WHERE user_id IS NOT NULL;

-- ──────────────────────────────────────────────────────────────────────
-- 3. talk_transcripts — saved per-utterance transcript + translation
-- ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS talk_transcripts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id         uuid NOT NULL REFERENCES talk_rooms(id) ON DELETE CASCADE,
    participant_id  uuid REFERENCES talk_participants(id) ON DELETE SET NULL,
    spoken_text     text NOT NULL,
    translated_text text,
    spoken_lang     text NOT NULL,
    translated_lang text,
    spoken_at       timestamptz NOT NULL DEFAULT now(),
    duration_ms     integer
);

CREATE INDEX IF NOT EXISTS talk_transcripts_room_idx        ON talk_transcripts (room_id, spoken_at);
CREATE INDEX IF NOT EXISTS talk_transcripts_participant_idx ON talk_transcripts (participant_id);

-- ──────────────────────────────────────────────────────────────────────
-- 4. talk_contacts — B2C address book (family / colleagues to call easily)
-- ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS talk_contacts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    contact_name    text NOT NULL,
    contact_email   text,
    contact_phone   text,
    preferred_lang  text NOT NULL,
    photo_url       text,
    last_called_at  timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS talk_contacts_owner_idx ON talk_contacts (owner_user_id, contact_name);

-- ──────────────────────────────────────────────────────────────────────
-- Row-level security policies
-- ──────────────────────────────────────────────────────────────────────

ALTER TABLE talk_rooms        ENABLE ROW LEVEL SECURITY;
ALTER TABLE talk_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE talk_transcripts  ENABLE ROW LEVEL SECURITY;
ALTER TABLE talk_contacts     ENABLE ROW LEVEL SECURITY;

-- For now, since we use service_role from the Flask backend, RLS is
-- effectively bypassed. Service-role bypasses RLS by design. We'll add
-- granular policies if/when we expose direct PostgREST access to clients.

-- Allow service role to do everything (the Flask backend uses service_role).
CREATE POLICY service_role_all_talk_rooms        ON talk_rooms
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_all_talk_participants ON talk_participants
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_all_talk_transcripts  ON talk_transcripts
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_all_talk_contacts     ON talk_contacts
    FOR ALL TO service_role USING (true) WITH CHECK (true);
