-- ============================================================================
-- Migration 002: enterprise_leads table
--
-- Purpose: capture sales leads from the "Talk to Sales" / Enterprise tier form
--          on the /pricing page. Used for high-value B2B prospects (BPOs,
--          call centers, large e-commerce sellers, Fortune 500).
--
-- How to run on Supabase:
--   1. Go to Supabase dashboard → SQL Editor
--   2. Paste the SQL below
--   3. Click "Run"
--
-- If you're on local SQLite via SQLAlchemy, the model in
-- app/models/enterprise_lead.py will create the table automatically on first
-- request via Base.metadata.create_all().
-- ============================================================================

CREATE TABLE IF NOT EXISTS enterprise_leads (
    lead_id        VARCHAR PRIMARY KEY,
    name           VARCHAR(200)  NOT NULL,
    email          VARCHAR(320)  NOT NULL,
    company        VARCHAR(200)  NOT NULL,
    job_title      VARCHAR(150),
    phone          VARCHAR(50),
    country        VARCHAR(100),
    num_agents     INTEGER,
    use_case       TEXT,
    source_plan    VARCHAR(50),
    status         VARCHAR(30) DEFAULT 'new',
    notes          TEXT,
    created_at     TIMESTAMPTZ DEFAULT now(),
    updated_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_enterprise_leads_email      ON enterprise_leads (email);
CREATE INDEX IF NOT EXISTS idx_enterprise_leads_status     ON enterprise_leads (status);
CREATE INDEX IF NOT EXISTS idx_enterprise_leads_created_at ON enterprise_leads (created_at DESC);

-- Auto-update updated_at on every row update
CREATE OR REPLACE FUNCTION update_enterprise_leads_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_enterprise_leads_updated_at ON enterprise_leads;
CREATE TRIGGER trg_enterprise_leads_updated_at
    BEFORE UPDATE ON enterprise_leads
    FOR EACH ROW EXECUTE FUNCTION update_enterprise_leads_updated_at();

-- Optional: enable Row Level Security (recommended on Supabase)
-- Uncomment if you want only authenticated admins to read these rows:
-- ALTER TABLE enterprise_leads ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Admins read leads"  ON enterprise_leads FOR SELECT USING (auth.role() = 'service_role');
-- CREATE POLICY "Anyone insert lead" ON enterprise_leads FOR INSERT WITH CHECK (true);
