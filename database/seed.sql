-- Initial Seed Data for CareerOS (Compatible with SQLite & PostgreSQL)

INSERT OR IGNORE INTO candidate_profiles (
  id, external_key, full_name, headline, location, target_roles, preferences, consent, active
) VALUES (
  'cand-001-aditya',
  'linkedin:aditya-pratama',
  'Aditya Pratama',
  'Senior Backend & AI Engineer',
  'Jakarta / Remote',
  '["Backend Engineer", "AI Systems Engineer", "Platform Engineer"]',
  '{"work_modes": ["remote", "hybrid"], "salary_min": 25000000, "currency": "IDR", "desired_tech": ["Python", "FastAPI", "PostgreSQL", "Docker", "LLM"]}',
  '{"require_human_approval": true, "auto_submit": false}',
  1
);

INSERT OR IGNORE INTO resume_versions (
  id, candidate_id, version_label, source_uri, extracted_text, structured_facts, content_hash, is_current
) VALUES (
  'res-001-aditya',
  'cand-001-aditya',
  'v2026.1-backend-ai',
  'uploads/aditya_cv_2026.pdf',
  'Experienced Backend Engineer with 5+ years building distributed services using Python, FastAPI, Docker, and PostgreSQL. Integrated LLM pipelines and autonomous agents.',
  '{"skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "n8n", "LLM", "Redis", "AWS"], "experience_years": 5, "verified_achievements": ["Membangun microservice backend dengan throughput 10k RPM.", "Mengimplementasikan pipeline orkestrator n8n dan database PostgreSQL.", "Mendesain skema database terdistribusi dan audit trail untuk kepatuhan SOC 2."]}',
  'hash-aditya-2026-v1',
  1
);

INSERT OR IGNORE INTO jobs (
  id, source, external_id, url, title, company, location, description, normalized, status
) VALUES (
  'job-seed-001',
  'remoteok',
  'rem-98210',
  'https://example.com/jobs/rem-98210',
  'Senior Python / AI Backend Engineer',
  'HyperScale Cloud',
  'Remote (APAC / Global)',
  'We are seeking a Senior Backend Engineer proficient in Python, FastAPI, Docker, and PostgreSQL to design scalable AI workflow agents and integrations.',
  '{"tech_stack": ["Python", "FastAPI", "PostgreSQL", "Docker", "LLM"], "min_experience": 4, "remote": true}',
  'discovered'
), (
  'job-seed-002',
  'arbeitnow',
  'arb-54122',
  'https://example.com/jobs/arb-54122',
  'Lead Platform & Systems Engineer',
  'Nova FinTech Labs',
  'Remote / Hybrid',
  'Looking for a Platform Engineer with deep expertise in Kubernetes, Go, and Terraform to lead cloud infrastructure.',
  '{"tech_stack": ["Go", "Kubernetes", "Terraform", "AWS"], "min_experience": 6, "remote": true}',
  'discovered'
);
