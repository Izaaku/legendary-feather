-- Migration 004: Switch billing from per-minute (rounded up) to per-second.
--
-- BEFORE: each F2F utterance consumed at least 1 full minute via
-- `users.minutes_used += max(1, ceil(chars / 750))`. Five short phrases
-- ("Hi.", "Hola.", "Yes.") emptied a 5-minute Free plan in seconds.
--
-- AFTER: we track actual speech-duration estimate per phrase
-- (chars / 12.5 ≈ 150 wpm) and accumulate it into `users.seconds_used`.
-- Plan totals stay in minutes (UX), the gate compares seconds_used vs
-- minutes_total * 60.
--
-- Backfill: seconds_used initialized from existing minutes_used so users
-- mid-cycle don't get a free reset. minutes_used remains as a legacy
-- mirror so any old code path that still reads it gets a sane value.
--
-- Safe to run multiple times (IF NOT EXISTS).

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS seconds_used INTEGER NOT NULL DEFAULT 0;

-- One-time backfill: convert existing minutes_used into seconds.
-- Only updates rows where seconds_used hasn't been set yet (still 0)
-- and the user has some minutes_used recorded — avoids re-running the
-- conversion on subsequent deploys.
UPDATE users
SET seconds_used = minutes_used * 60
WHERE seconds_used = 0
  AND minutes_used > 0;
