"""Database Initializer for AI Career Agent (CareerOS).

Supports PostgreSQL (via psycopg2) when configured,
with automatic fallback to local SQLite (database/career_agent.db).
"""

import os
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "database"
SQLITE_PATH = DB_DIR / "career_agent.db"
SCHEMA_SQL = DB_DIR / "schema.sql"
SEED_SQL = DB_DIR / "seed.sql"

SQLITE_SCHEMA = """
-- SQLite Schema equivalent to PostgreSQL schema.sql
PRAGMA foreign_keys = ON;

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
"""


def init_sqlite() -> None:
    print(f"Initializing SQLite database at: {SQLITE_PATH}")
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    try:
        cursor = conn.cursor()
        cursor.executescript(SQLITE_SCHEMA)
        conn.commit()
        print("SQLite schema initialized successfully.")

        if SEED_SQL.exists():
            seed_content = SEED_SQL.read_text(encoding="utf-8")
            cursor.executescript(seed_content)
            conn.commit()
            print("SQLite seed data populated successfully.")
    finally:
        conn.close()


def try_init_postgres() -> bool:
    pg_host = os.getenv("POSTGRES_HOST")
    if not pg_host:
        return False

    try:
        import psycopg2  # type: ignore
    except ImportError:
        print("psycopg2 not installed; falling back to SQLite.")
        return False

    try:
        conn = psycopg2.connect(
            host=pg_host,
            port=os.getenv("POSTGRES_PORT", 5432),
            dbname=os.getenv("POSTGRES_DB", "career_agent"),
            user=os.getenv("POSTGRES_USER", "career_agent"),
            password=os.getenv("POSTGRES_PASSWORD", "career_agent"),
            connect_timeout=3,
        )
        with conn.cursor() as cur:
            schema_content = SCHEMA_SQL.read_text(encoding="utf-8")
            cur.execute(schema_content)
            conn.commit()
            print("PostgreSQL schema initialized successfully.")
        conn.close()
        return True
    except Exception as exc:
        print(f"PostgreSQL connection failed ({exc}). Falling back to SQLite.")
        return False


def main() -> None:
    if not try_init_postgres():
        init_sqlite()


if __name__ == "__main__":
    main()
