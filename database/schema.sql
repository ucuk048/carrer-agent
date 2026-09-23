-- ============================================================================
-- Career Agent Database Schema
-- Compatible with PostgreSQL & SQLite (3.35+)
-- ============================================================================

-- 1. Candidate Profiles
CREATE TABLE IF NOT EXISTS candidate_profiles (
  id TEXT PRIMARY KEY,
  external_key TEXT UNIQUE NOT NULL,
  full_name TEXT NOT NULL,
  headline TEXT,
  location TEXT,
  target_roles TEXT NOT NULL DEFAULT '[]',
  preferences TEXT NOT NULL DEFAULT '{}',
  consent TEXT NOT NULL DEFAULT '{"require_human_approval":true,"auto_submit":false}',
  active INTEGER NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Resume Versions
CREATE TABLE IF NOT EXISTS resume_versions (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
  version_label TEXT NOT NULL,
  source_uri TEXT,
  extracted_text TEXT NOT NULL,
  structured_facts TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Jobs Radar
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  company TEXT,
  location TEXT,
  description TEXT,
  normalized TEXT NOT NULL DEFAULT '{}',
  risk_flags TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'discovered',
  first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source, external_id)
);

-- 4. Job Matches & AI Scoring
CREATE TABLE IF NOT EXISTS job_matches (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  score REAL NOT NULL,
  confidence TEXT NOT NULL,
  evidence TEXT NOT NULL DEFAULT '{}',
  missing_requirements TEXT NOT NULL DEFAULT '[]',
  model_version TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(candidate_id, job_id)
);

-- 5. Applications
CREATE TABLE IF NOT EXISTS applications (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  resume_version_id TEXT REFERENCES resume_versions(id),
  status TEXT NOT NULL DEFAULT 'draft',
  artifacts TEXT NOT NULL DEFAULT '{}',
  notes TEXT,
  submitted_at DATETIME,
  next_follow_up_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(candidate_id, job_id)
);

-- 6. Human Approvals
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending',
  requested_artifacts TEXT NOT NULL DEFAULT '{}',
  reviewer TEXT,
  decision_reason TEXT,
  expires_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  decided_at DATETIME
);

-- 7. Audit Events & Logs
CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY,
  actor_type TEXT NOT NULL,
  actor_id TEXT,
  event_type TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  payload TEXT NOT NULL DEFAULT '{}',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. System Settings & Configurations
CREATE TABLE IF NOT EXISTS system_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for Query Performance
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_job_matches_score ON job_matches(score);
CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at);
