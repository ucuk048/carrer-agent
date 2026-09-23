"""Career Agent API & Web Server.

Serves static landing page and onboarding portal.
Provides REST API endpoints for candidate onboarding, job matching,
human-in-the-loop approval, and n8n webhook communication.
Uses standard Python library (no external dependency required).
"""

import base64
import email
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import parse_qs, urlparse

from linkedin_scraper import scrape_and_ingest_linkedin
import profile_extractor
import linkedin_easy_apply
import linkedin_manual_login
import external_apply

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database" / "career_agent.db"
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

manual_login_state = {
    "status": "idle",
    "message": "Belum dimulai",
    "updated_at": 0,
    "result": None
}


def load_dotenv():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and k not in os.environ:
                os.environ[k] = v


load_dotenv()


def generate_and_save_candidate_cv(cand, resume=None) -> Optional[Path]:
    """Generates an official, ATS-compliant CV PDF strictly synchronized with the candidate's profile."""
    try:
        cand_dict = dict(cand) if cand else {}
        cand_id = cand_dict.get("id") or f"cand-{uuid.uuid4().hex[:8]}"
        full_name = cand_dict.get("full_name") or "Pelamar Kerja"
        headline = cand_dict.get("headline") or "Profesional & Rekayasa Perangkat Lunak"
        location = cand_dict.get("location") or "Indonesia"
        linkedin_url = cand_dict.get("external_key") or ""

        # Extract skills and achievements from facts
        facts = {}
        if resume:
            try:
                facts = json.loads(resume["structured_facts"]) if resume["structured_facts"] else {}
            except Exception:
                facts = {}

        skills = facts.get("skills", [])
        if not skills and cand_dict.get("target_roles"):
            try:
                skills = json.loads(cand_dict["target_roles"])
            except Exception:
                pass
        if not skills:
            skills = ["Problem Solving", "Komunikasi", "Adaptabilitas"]

        achievements = facts.get("verified_achievements", [])
        if not achievements:
            achievements = [
                f"Profil terverifikasi resmi untuk {full_name} di platform Career Agent.",
                f"Fokus kompetensi profesional di bidang {headline}."
            ]

        summary = facts.get("summary") or f"Profesional berdedikasi tinggi dengan fokus kompetensi di bidang {headline}. Memiliki keahlian terverifikasi dalam {', '.join(skills[:5])}."

        skills_pills = "".join([f'<span class="skill-pill">{html.escape(str(s))}</span>' for s in skills])
        achieve_items = "".join([f'<li>{html.escape(str(a))}</li>' for a in achievements])

        cv_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 18mm 20mm; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; line-height: 1.5; margin: 0; padding: 0; }}
  .name {{ font-size: 24px; font-weight: 700; color: #0f172a; margin-bottom: 4px; }}
  .headline {{ font-size: 14px; font-weight: 600; color: #0284c7; margin-bottom: 12px; }}
  .contact-bar {{ font-size: 12px; color: #64748b; margin-bottom: 16px; display: flex; flex-wrap: wrap; gap: 10px; }}
  .divider {{ border-top: 1px solid #e2e8f0; margin: 14px 0; }}
  .section-title {{ font-size: 12.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #334155; margin-bottom: 8px; }}
  .summary {{ font-size: 12px; color: #334155; margin-bottom: 14px; text-align: justify; }}
  .skills-box {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }}
  .skill-pill {{ background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 500; color: #1e293b; }}
  .achieve-list {{ margin: 0; padding-left: 18px; font-size: 12px; color: #334155; }}
  .achieve-list li {{ margin-bottom: 6px; }}
  .footer {{ margin-top: 36px; padding-top: 10px; border-top: 1px dashed #cbd5e1; font-size: 10px; color: #94a3b8; display: flex; justify-content: space-between; }}
</style>
</head>
<body>
  <div class="name">{html.escape(full_name)}</div>
  <div class="headline">{html.escape(headline)}</div>
  <div class="contact-bar">
    <span>Lokasi: {html.escape(location)}</span>
    {"<span>•</span><span>LinkedIn: " + html.escape(linkedin_url) + "</span>" if linkedin_url else ""}
  </div>
  <div class="divider"></div>
  <div class="section-title">Ringkasan Profil</div>
  <div class="summary">{html.escape(summary)}</div>
  <div class="section-title">Keahlian Utama</div>
  <div class="skills-box">{skills_pills}</div>
  <div class="section-title">Pengalaman & Rekam Jejak</div>
  <ul class="achieve-list">{achieve_items}</ul>
  <div class="footer">
    <span>Career Agent CareerOS — Verified Profile</span>
    <span>Sinkronisasi Resmi Data Profil LinkedIn</span>
  </div>
</body>
</html>"""

        resumes_dir = ROOT / "uploads" / "resumes"
        resumes_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', full_name.lower().strip()) or "candidate"
        out_path = resumes_dir / f"{cand_id}_cv_{safe_name}.pdf"

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = b.new_page()
            page.set_content(cv_html)
            page.pdf(path=str(out_path), format="A4", print_background=True)
            b.close()

        # Update resume_versions in DB
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE resume_versions SET is_current = 0 WHERE candidate_id = ?", (cand_id,))
            res_id = f"res-{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO resume_versions (id, candidate_id, version_label, source_uri, extracted_text, structured_facts, content_hash, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                res_id,
                cand_id,
                f"CV_{safe_name}.pdf",
                str(out_path.resolve()),
                summary,
                json.dumps({"skills": skills, "verified_achievements": achievements, "summary": summary}),
                uuid.uuid4().hex
            ))
            conn.commit()

        return out_path
    except Exception as e:
        print(f"[Error] Gagal generate candidate CV: {e}")
        return None


def call_gemini(prompt: str, system_instruction: str = "", max_retries: int = 2) -> str:
    """Invokes Google Gemini API directly using Python standard library with zero-latency configuration."""
    import time
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return ""
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": api_key,
    }
    gen_config = {
        "temperature": 0.4,
        "maxOutputTokens": 1000
    }
    if "3.8" in model:
        gen_config["thinkingConfig"] = {"thinkingBudget": 0}

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config
    }
    if system_instruction:
        body["system_instruction"] = {"parts": [{"text": system_instruction}]}

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.loads(res.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "text" in part:
                            return part["text"].strip()
        except Exception as exc:
            if attempt < max_retries - 1:
                time.sleep(1.0)
                continue
            print(f"[Gemini API Notice] {exc}")
    return ""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class CareerHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def send_json(self, data, status=HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        # API Routes
        if route == "/api/status":
            self.handle_api_status()
            return
        elif route == "/api/jobs":
            self.handle_api_jobs()
            return
        elif route == "/api/applications":
            self.handle_api_applications()
            return
        elif route == "/api/audit-events":
            self.handle_api_audit_events()
            return
        elif route == "/api/profile":
            self.handle_api_get_profile()
            return
        elif route == "/api/profile/cv":
            self.handle_api_get_cv()
            return
        elif route == "/api/system/diagnostics":
            self.handle_api_diagnostics()
            return
        elif route == "/api/settings/credentials":
            self.handle_api_get_credentials()
            return
        elif route == "/api/linkedin/manual-login/status":
            self.send_json(manual_login_state)
            return
        elif route == "/api/jobs/keywords-catalog":
            self.handle_api_keywords_catalog()
            return

        # Static Page Routing
        super().do_GET()

    def translate_path(self, path):
        route = urlparse(path).path
        if route in ("/", "/index.html"):
            return str(ROOT / "landing-page" / "index.html")
        if route in ("/dashboard", "/dashboard/"):
            return str(ROOT / "dashboard" / "index.html")
        if route.startswith("/dashboard/"):
            return str(ROOT / "dashboard" / route.removeprefix("/dashboard/"))
        if route.startswith("/landing-page/"):
            return str(ROOT / route.removeprefix("/"))

        target = ROOT / route.lstrip("/")
        if not target.exists():
            # Check in landing-page
            lp_target = ROOT / "landing-page" / route.lstrip("/")
            if lp_target.exists():
                return str(lp_target)
            # Check in dashboard
            db_target = ROOT / "dashboard" / route.lstrip("/")
            if db_target.exists():
                return str(db_target)
        return str(target)

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/onboarding":
            self.handle_api_onboarding()
        elif route == "/api/approval":
            self.handle_api_approval()
        elif route == "/api/run-cycle":
            self.handle_api_run_cycle()
        elif route == "/api/jobs/add":
            self.handle_api_add_job()
        elif route == "/api/jobs/parse-ai":
            self.handle_api_parse_job_ai()
        elif route == "/api/profile/update":
            self.handle_api_update_profile()
        elif route == "/api/applications/update-draft":
            self.handle_api_update_draft()
        elif route == "/api/applications/regenerate":
            self.handle_api_regenerate_draft()
        elif route == "/api/applications/update-stage":
            self.handle_api_update_stage()
        elif route == "/api/applications/delete":
            self.handle_api_delete_applications()
        elif route == "/api/copilot/chat":
            self.handle_api_copilot_chat()
        elif route == "/api/jobs/scrape-linkedin":
            self.handle_api_scrape_linkedin()
        elif route == "/api/jobs/bulk-apply":
            self.handle_api_bulk_apply()
        elif route == "/api/pipeline/auto-chain":
            self.handle_api_auto_chain()
        elif route == "/api/profile/import-url":
            self.handle_api_import_profile()
        elif route == "/api/profile/upload-resume":
            self.handle_api_upload_resume()
        elif route == "/api/settings/save-credentials":
            self.handle_api_save_credentials()
        elif route == "/api/linkedin/verify-session":
            self.handle_api_verify_linkedin_session()
        elif route == "/api/jobs/easy-apply":
            self.handle_api_easy_apply()
        elif route == "/api/jobs/external-apply":
            self.handle_api_external_apply()
        elif route == "/api/linkedin/manual-login/start":
            self.handle_api_start_manual_login()
        elif route == "/api/linkedin/manual-login/cancel":
            self.handle_api_cancel_manual_login()
        elif route == "/api/linkedin/auth/login":
            self.handle_api_auth_login()
        elif route == "/api/linkedin/disconnect":
            self.handle_api_linkedin_disconnect()
        elif route == "/api/profile/sync-linkedin":
            self.handle_api_sync_linkedin_profile()
        elif route == "/api/linkedin/chrome-sync":
            self.handle_api_chrome_sync()
        elif route == "/api/linkedin/dom-sync":
            self.handle_api_dom_sync()
        else:
            self.send_json({"error": "Endpoint tidak ditemukan."}, status=HTTPStatus.NOT_FOUND)

    def handle_api_status(self):
        try:
            with get_db() as conn:
                cur = conn.cursor()
                cand_count = cur.execute("SELECT COUNT(*) FROM candidate_profiles").fetchone()[0]
                job_count = cur.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                app_count = cur.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
                approval_count = cur.execute("SELECT COUNT(*) FROM approvals WHERE status='pending'").fetchone()[0]

            self.send_json({
                "status": "online",
                "system": "Career Agent AI",
                "database": "sqlite",
                "counts": {
                    "candidates": cand_count,
                    "jobs": job_count,
                    "applications": app_count,
                    "pending_approvals": approval_count,
                },
            })
        except Exception as exc:
            self.send_json({"status": "error", "message": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_jobs(self):
        try:
            with get_db() as conn:
                cur = conn.cursor()
                rows = cur.execute("""
                    SELECT j.id, j.source, j.title, j.company, j.location, j.url, j.status, j.description,
                           MAX(jm.score) as score, jm.confidence, jm.missing_requirements,
                           a.id as application_id, a.status as application_status
                    FROM jobs j
                    LEFT JOIN job_matches jm ON j.id = jm.job_id
                    LEFT JOIN applications a ON j.id = a.job_id
                    GROUP BY j.id
                    ORDER BY score DESC NULLS LAST, j.first_seen_at DESC
                """).fetchall()

            jobs = [dict(r) for r in rows]
            self.send_json({"jobs": jobs})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_applications(self):
        try:
            with get_db() as conn:
                cur = conn.cursor()
                rows = cur.execute("""
                    SELECT a.id, a.status, a.artifacts, a.notes, a.created_at,
                           j.title as job_title, j.company as job_company, j.url as job_url,
                           ap.status as approval_status
                    FROM applications a
                    JOIN jobs j ON a.job_id = j.id
                    LEFT JOIN approvals ap ON a.id = ap.application_id
                    ORDER BY a.created_at DESC
                """).fetchall()

            apps = []
            for r in rows:
                item = dict(r)
                if item["artifacts"]:
                    try:
                        item["artifacts"] = json.loads(item["artifacts"])
                    except Exception:
                        pass
                apps.append(item)
            self.send_json({"applications": apps})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_delete_applications(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = {}
            if content_length > 0:
                data = json.loads(self.rfile.read(content_length).decode("utf-8"))

            raw_job_ids = data.get("job_ids", [])
            raw_app_ids = data.get("application_ids", [])

            if isinstance(raw_job_ids, str) and raw_job_ids:
                raw_job_ids = [raw_job_ids]
            if isinstance(raw_app_ids, str) and raw_app_ids:
                raw_app_ids = [raw_app_ids]

            job_ids = list(set([str(j).strip() for j in raw_job_ids if j]))
            app_ids = list(set([str(a).strip() for a in raw_app_ids if a]))

            deleted_jobs = 0
            deleted_apps = 0

            with get_db() as conn:
                cur = conn.cursor()
                if app_ids:
                    placeholders = ",".join("?" for _ in app_ids)
                    rows = cur.execute(f"SELECT job_id FROM applications WHERE id IN ({placeholders})", app_ids).fetchall()
                    for r in rows:
                        if r["job_id"] and r["job_id"] not in job_ids:
                            job_ids.append(r["job_id"])

                    cur.execute(f"DELETE FROM approvals WHERE application_id IN ({placeholders})", app_ids)
                    cur.execute(f"DELETE FROM applications WHERE id IN ({placeholders})", app_ids)
                    deleted_apps += cur.rowcount

                if job_ids:
                    placeholders = ",".join("?" for _ in job_ids)
                    cur.execute(f"DELETE FROM approvals WHERE application_id IN (SELECT id FROM applications WHERE job_id IN ({placeholders}))", job_ids)
                    cur.execute(f"DELETE FROM applications WHERE job_id IN ({placeholders})", job_ids)
                    deleted_apps += cur.rowcount
                    cur.execute(f"DELETE FROM job_matches WHERE job_id IN ({placeholders})", job_ids)
                    cur.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids)
                    deleted_jobs += cur.rowcount

                conn.commit()

            self.send_json({
                "success": True,
                "deleted_jobs": deleted_jobs,
                "deleted_applications": deleted_apps,
                "message": f"Berhasil menghapus {deleted_jobs or deleted_apps} data."
            })
        except Exception as exc:
            self.send_json({"success": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_onboarding(self):
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))

        body = self.rfile.read(content_length)

        linkedin_url = ""
        full_name = ""
        target_roles = ["Software Engineer"]
        uploaded_filename = ""
        extracted_text = ""

        if "multipart/form-data" in content_type:
            # Parse multipart message using standard email parser
            msg_bytes = (
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
            )
            parsed_msg = email.message_from_bytes(msg_bytes)

            for part in parsed_msg.get_payload():
                disp = part.get("Content-Disposition", "")
                name = None
                filename = None
                for param in disp.split(";"):
                    param = param.strip()
                    if param.startswith("name="):
                        name = param.split("=")[1].strip('"\'')
                    elif param.startswith("filename="):
                        filename = param.split("=")[1].strip('"\'')

                if name == "linkedin_url":
                    linkedin_url = part.get_payload(decode=True).decode("utf-8", errors="replace").strip()
                elif name == "full_name":
                    full_name = part.get_payload(decode=True).decode("utf-8", errors="replace").strip()
                elif name == "resume_file" and filename:
                    uploaded_filename = filename
                    file_bytes = part.get_payload(decode=True)
                    saved_path = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{filename}"
                    saved_path.write_bytes(file_bytes)
                    extracted_text = f"File: {filename}. Ukuran: {len(file_bytes)} bytes."
        else:
            try:
                data = json.loads(body.decode("utf-8"))
                linkedin_url = data.get("linkedin_url", "")
                full_name = data.get("full_name", "")
                extracted_text = data.get("resume_text", "")
            except Exception:
                pass

        if not full_name or full_name.lower().startswith("candidate"):
            if linkedin_url:
                try:
                    import re
                    parts = urlparse(linkedin_url).path.strip("/").split("/")
                    if len(parts) >= 2 and parts[0] == "in":
                        slug = re.sub(r"-[0-9a-fA-F]{6,}$", "", parts[1])
                        slug = re.sub(r"-\d+$", "", slug)
                        cleaned_name = slug.replace("-", " ").title().strip()
                        if cleaned_name and len(cleaned_name) > 1:
                            full_name = cleaned_name
                except Exception:
                    pass
            if not full_name or full_name.lower().startswith("candidate"):
                with get_db() as conn:
                    cur = conn.cursor()
                    row = cur.execute("SELECT full_name FROM candidate_profiles WHERE active=1 AND full_name NOT LIKE 'Candidate%' AND full_name NOT LIKE 'Kandidat%' LIMIT 1").fetchone()
                    full_name = (row and row[0]) or "Kandidat Pelamar"

        candidate_id = f"cand-{uuid.uuid4().hex[:8]}"
        external_key = linkedin_url or f"manual:{candidate_id}"
        default_headline = f"{target_roles[0]} · Profesional Berpengalaman" if target_roles else "Profesional & Pencari Kerja"

        with get_db() as conn:
            cur = conn.cursor()
            existing_cand = cur.execute("SELECT id FROM candidate_profiles WHERE external_key = ?", (external_key,)).fetchone()
            if existing_cand:
                candidate_id = existing_cand[0]
                cur.execute("""
                    UPDATE candidate_profiles
                    SET full_name = ?, target_roles = ?, active = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (full_name, json.dumps(target_roles), candidate_id))
            else:
                cur.execute("""
                    INSERT INTO candidate_profiles (
                        id, external_key, full_name, headline, target_roles, preferences, consent, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    candidate_id,
                    external_key,
                    full_name,
                    default_headline,
                    json.dumps(target_roles),
                    json.dumps({"work_modes": ["remote", "hybrid"]}),
                    json.dumps({"require_human_approval": True, "auto_submit": False}),
                ))

            resume_id = f"res-{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO resume_versions (
                    id, candidate_id, version_label, source_uri, extracted_text, structured_facts, content_hash, is_current
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                resume_id,
                candidate_id,
                "initial-upload",
                uploaded_filename,
                extracted_text or "Uploaded via onboarding portal",
                json.dumps({
                    "skills": ["Python", "FastAPI", "SQL", "Docker", "Git"],
                    "verified_achievements": [f"Profil diunggah dari {uploaded_filename or linkedin_url}"]
                }),
                uuid.uuid4().hex,
            ))

            cur.execute("""
                INSERT INTO audit_events (
                    id, actor_type, actor_id, event_type, entity_type, entity_id, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                f"aud-{uuid.uuid4().hex[:8]}",
                "candidate",
                candidate_id,
                "candidate_onboarded",
                "candidate_profiles",
                candidate_id,
                json.dumps({"name": full_name, "linkedin": linkedin_url, "file": uploaded_filename}),
            ))
            conn.commit()

        self.send_json({
            "success": True,
            "candidate_id": candidate_id,
            "full_name": full_name,
            "message": f"Profil {full_name} berhasil disimpan dan masuk ke antrean Career Agent.",
        })

    def handle_api_approval(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))

            application_id = data.get("application_id")
            decision = data.get("decision")  # approved, rejected, changes_requested
            reviewer = data.get("reviewer", "Aditya")
            reason = data.get("reason", "")

            if not application_id or decision not in ("approved", "rejected", "changes_requested"):
                self.send_json({"error": "application_id dan decision valid diperlukan."}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                app_status = "approved" if decision == "approved" else "rejected"
                cur.execute("UPDATE applications SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (app_status, application_id))
                cur.execute("""
                    UPDATE approvals
                    SET status = ?, reviewer = ?, decision_reason = ?, decided_at = CURRENT_TIMESTAMP
                    WHERE application_id = ?
                """, (decision, reviewer, reason, application_id))

                cur.execute("""
                    INSERT INTO audit_events (
                        id, actor_type, actor_id, event_type, entity_type, entity_id, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"aud-{uuid.uuid4().hex[:8]}",
                    "human_reviewer",
                    reviewer,
                    f"application_{decision}",
                    "applications",
                    application_id,
                    json.dumps({"decision": decision, "reason": reason}),
                ))
                conn.commit()

            self.send_json({
                "success": True,
                "application_id": application_id,
                "decision": decision,
                "message": f"Lamaran telah berstatus: {decision} oleh {reviewer}.",
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_run_cycle(self):
        """Simulates or runs the full intelligence cycle: Match candidate with jobs, generate draft, create pending approval."""
        try:
            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                if not cand:
                    self.send_json({"error": "Tidak ada profil kandidat aktif."}, status=HTTPStatus.BAD_REQUEST)
                    return

                resume = cur.execute("SELECT * FROM resume_versions WHERE candidate_id = ? AND is_current=1 LIMIT 1", (cand["id"],)).fetchone()
                facts = json.loads(resume["structured_facts"]) if resume else {"skills": ["Python", "FastAPI"]}
                cand_skills = [s.lower() for s in facts.get("skills", [])]

                jobs = cur.execute("SELECT * FROM jobs WHERE status = 'discovered'").fetchall()
                created_drafts = []

                target_roles = json.loads(cand["target_roles"]) if cand["target_roles"] else ["Backend Engineer"]
                preferences = json.loads(cand["preferences"]) if cand["preferences"] else {}
                preferred_modes = [m.lower() for m in preferences.get("work_modes", ["remote"])]

                for job in jobs:
                    job_text = f"{job['title']} {job['description']}".lower()
                    matched = [s for s in cand_skills if s in job_text]
                    
                    # 1. Skill match (max 40)
                    skill_score = min(40, int((len(matched) / max(min(len(cand_skills), 5), 1)) * 40))
                    
                    # 2. Role / Title match (max 20)
                    role_score = 20 if any(r.lower() in job["title"].lower() for r in target_roles) else 0
                    
                    # 3. Location / Remote arrangement match (max 15)
                    loc_text = f"{job['location']} {job['description']}".lower()
                    loc_score = 15 if any(m in loc_text for m in preferred_modes) else 5
                    
                    # 4. Domain & Experience match (max 15)
                    domain_score = 15 if ("senior" in job["title"].lower() or "ai" in job["title"].lower()) else 5
                    
                    # 5. Base alignment (max 10)
                    base_score = 10
                    
                    score = min(100, skill_score + role_score + loc_score + domain_score + base_score)
                    confidence = "high" if score >= 70 else ("medium" if score >= 50 else "low")

                    match_id = f"jm-{uuid.uuid4().hex[:8]}"
                    cur.execute("""
                        INSERT OR REPLACE INTO job_matches (
                            id, candidate_id, job_id, score, confidence, evidence, missing_requirements
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        match_id,
                        cand["id"],
                        job["id"],
                        score,
                        confidence,
                        json.dumps([{"skill": s, "source": "resume"} for s in matched]),
                        json.dumps([s for s in cand_skills if s not in matched]),
                    ))

                    # If score >= 60, create application draft and pending approval
                    if score >= 60:
                        app_id = f"app-{uuid.uuid4().hex[:8]}"

                        # Tailor cover letter via Gemini LLM if API key available
                        gemini_prompt = (
                            f"Kamu adalah AI Career Agent profesional. Tuliskan draf cover letter singkat (2-3 paragraf), "
                            f"formal, persuasif, dan elegan dalam Bahasa Indonesia untuk kandidat berikut:\n"
                            f"Nama: {cand['full_name']}\n"
                            f"Headline: {cand['headline']}\n"
                            f"Skill Cocok: {', '.join(matched)}\n"
                            f"Fakta Terverifikasi CV: {json.dumps(facts.get('verified_achievements', []))}\n\n"
                            f"Target Lowongan:\n"
                            f"Posisi: {job['title']}\n"
                            f"Perusahaan: {job['company']}\n"
                            f"Deskripsi: {job['description']}\n\n"
                            f"Aturan mutlak: Jangan mengarang fakta, angka, atau perusahaan yang tidak ada di data CV. "
                            f"Jangan gunakan placeholder seperti [Company] atau [Nama]. Tulis langsung siap kirim."
                        )
                        ai_generated_letter = call_gemini(gemini_prompt)

                        cover_letter = ai_generated_letter if ai_generated_letter else (
                            f"Yth. Tim Rekrutmen {job['company']},\n\n"
                            f"Saya tertarik melamar posisi {job['title']}. "
                            f"Keahlian terverifikasi saya mencakup {', '.join(matched[:4])}, "
                            f"yang selaras dengan kebutuhan peran ini.\n\n"
                            f"Draf ini dibuat berdasarkan profil terverifikasi kandidat {cand['full_name']}."
                        )

                        cur.execute("""
                            INSERT OR REPLACE INTO applications (
                                id, candidate_id, job_id, resume_version_id, status, artifacts, notes
                            ) VALUES (?, ?, ?, ?, 'pending_approval', ?, ?)
                        """, (
                            app_id,
                            cand["id"],
                            job["id"],
                            resume["id"] if resume else None,
                            json.dumps({
                                "cover_letter": cover_letter,
                                "matched_skills": matched,
                                "score": score,
                                "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite") if ai_generated_letter else "deterministic"
                            }),
                            f"Match score: {score}/100 (Model: {os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite') if ai_generated_letter else 'Rule-based'})",
                        ))

                        appr_id = f"appr-{uuid.uuid4().hex[:8]}"
                        cur.execute("""
                            INSERT OR REPLACE INTO approvals (
                                id, application_id, status, requested_artifacts, reviewer
                            ) VALUES (?, ?, 'pending', ?, 'Aditya')
                        """, (
                            appr_id,
                            app_id,
                            json.dumps({"cover_letter": cover_letter}),
                        ))
                        created_drafts.append({"application_id": app_id, "job_title": job["title"], "score": score})

                conn.commit()

            self.send_json({
                "success": True,
                "candidate": cand["full_name"],
                "drafts_created": len(created_drafts),
                "items": created_drafts,
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_audit_events(self):
        try:
            with get_db() as conn:
                cur = conn.cursor()
                rows = cur.execute("""
                    SELECT id, actor_type, actor_id, event_type, entity_type, entity_id, payload, created_at
                    FROM audit_events
                    ORDER BY created_at DESC
                    LIMIT 20
                """).fetchall()
            events = []
            for r in rows:
                item = dict(r)
                if item["payload"]:
                    try:
                        item["payload"] = json.loads(item["payload"])
                    except Exception:
                        pass
                events.append(item)
            self.send_json({"audit_events": events})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_add_job(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            title = data.get("title", "").strip()
            company = data.get("company", "Perusahaan").strip()
            url = data.get("url", "").strip()
            description = data.get("description", "").strip()
            location = data.get("location", "Remote").strip()

            if not title:
                self.send_json({"error": "Judul lowongan wajib diisi."}, status=HTTPStatus.BAD_REQUEST)
                return

            job_id = f"job-{uuid.uuid4().hex[:8]}"
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO jobs (id, source, external_id, url, title, company, location, description, status)
                    VALUES (?, 'web_manual', ?, ?, ?, ?, ?, ?, 'discovered')
                """, (job_id, job_id, url, title, company, location, description))
                cur.execute("""
                    INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
                    VALUES (?, 'user', 'web_user', 'job_added', 'jobs', ?, ?)
                """, (f"aud-{uuid.uuid4().hex[:8]}", job_id, json.dumps({"title": title, "company": company})))
                conn.commit()

            self.send_json({
                "success": True,
                "job_id": job_id,
                "message": f"Lowongan '{title}' di {company} berhasil ditambahkan dan siap dievaluasi oleh Gemini."
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_get_profile(self):
        try:
            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                if not cand:
                    self.send_json({"candidate": None, "skills": [], "achievements": []})
                    return

                resume = cur.execute("SELECT * FROM resume_versions WHERE candidate_id = ? AND is_current=1 LIMIT 1", (cand["id"],)).fetchone()
                facts = json.loads(resume["structured_facts"]) if (resume and resume["structured_facts"]) else {}
                skills = facts.get("skills", [])
                achievements = facts.get("verified_achievements", [])
                target_roles = json.loads(cand["target_roles"]) if cand["target_roles"] else ["Software Engineer"]
                preferences = json.loads(cand["preferences"]) if cand["preferences"] else {}
                summary = facts.get("summary", "")

                resume_info = None
                resumes_dir = ROOT / "uploads" / "resumes"
                resume_file_path = None
                if resume and resume["source_uri"]:
                    p_src = Path(resume["source_uri"])
                    if p_src.is_file() and p_src.stat().st_size > 500:
                        resume_file_path = p_src

                if not resume_file_path and cand["id"]:
                    cand_files = sorted(
                        [p for p in resumes_dir.glob(f"{cand['id']}*.pdf") if p.stat().st_size > 500],
                        key=lambda p: p.stat().st_mtime,
                        reverse=True
                    )
                    if cand_files:
                        resume_file_path = cand_files[0]

                if not resume_file_path and cand["id"]:
                    resume_file_path = generate_and_save_candidate_cv(cand, resume)

                if resume or resume_file_path:
                    raw_filename = resume_file_path.name if resume_file_path else (resume["version_label"] if (resume and resume["version_label"]) else "Resume.pdf")
                    display_filename = raw_filename
                    if resume_file_path and cand["id"] and raw_filename.startswith(f"{cand['id']}_"):
                        display_filename = raw_filename[len(f"{cand['id']}_"):]
                    resume_info = {
                        "filename": display_filename,
                        "raw_filename": raw_filename,
                        "source_uri": str(resume_file_path.resolve()) if resume_file_path else (resume["source_uri"] if resume else ""),
                        "version_label": resume["version_label"] if resume else display_filename,
                        "updated_at": resume["created_at"] if resume else "",
                        "file_url": f"/api/profile/cv?candidate_id={cand['id']}",
                        "has_file": bool(resume_file_path and resume_file_path.exists() and resume_file_path.stat().st_size > 500)
                    }

            self.send_json({
                "candidate": {
                    "id": cand["id"],
                    "full_name": cand["full_name"],
                    "headline": cand["headline"],
                    "location": cand["location"] if cand["location"] else "Indonesia",
                    "target_roles": target_roles,
                    "preferences": preferences,
                    "external_key": cand["external_key"],
                    "avatar_url": cand["avatar_url"] if "avatar_url" in cand.keys() and cand["avatar_url"] else preferences.get("avatar_url", ""),
                    "created_at": cand["created_at"]
                },
                "skills": skills,
                "achievements": achievements,
                "summary": summary,
                "resume": resume_info
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_update_profile(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))

            full_name = data.get("full_name", "").strip()
            headline = data.get("headline", "").strip()
            target_roles = data.get("target_roles", [])
            skills = data.get("skills", [])
            work_modes = data.get("work_modes", ["remote"])
            summary = data.get("summary", "").strip()
            achievements = data.get("achievements", [])
            if isinstance(achievements, str):
                achievements = [a.strip() for a in achievements.split("\n") if a.strip()]

            if isinstance(target_roles, str):
                target_roles = [r.strip() for r in target_roles.split(",") if r.strip()]
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.split(",") if s.strip()]
            if isinstance(work_modes, str):
                work_modes = [m.strip() for m in work_modes.split(",") if m.strip()]

            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT id FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                if not cand:
                    self.send_json({"error": "Tidak ada profil kandidat aktif."}, status=HTTPStatus.BAD_REQUEST)
                    return

                candidate_id = cand["id"]
                pref_obj = {"work_modes": work_modes}
                if "experience_years" in data:
                    pref_obj["experience_years"] = data["experience_years"]
                if "expected_salary" in data:
                    pref_obj["expected_salary"] = data["expected_salary"]

                location = data.get("location", "").strip()

                cur.execute("""
                    UPDATE candidate_profiles
                    SET full_name = ?, headline = ?, location = ?, target_roles = ?, preferences = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    full_name or "Kandidat Pelamar",
                    headline or "Profesional & Pencari Kerja",
                    location or "Indonesia",
                    json.dumps(target_roles),
                    json.dumps(pref_obj),
                    candidate_id
                ))

                phone = data.get("phone", "").strip()
                if phone and phone != "0" and len(phone) >= 8:
                    cur.execute("""
                        INSERT INTO system_settings (key, value, updated_at)
                        VALUES ('candidate_phone', ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                    """, (phone,))

                # Update current resume facts with sanitized skills
                resume = cur.execute("SELECT id, structured_facts FROM resume_versions WHERE candidate_id = ? AND is_current=1 LIMIT 1", (candidate_id,)).fetchone()
                if resume:
                    facts = json.loads(resume["structured_facts"]) if resume["structured_facts"] else {}
                    sanitized_skills = [s.strip() for s in skills if len(s.strip()) > 1 and not re.match(r'^[a-zA-Z]$', s.strip())]
                    facts["skills"] = sanitized_skills
                    facts["summary"] = summary
                    if achievements:
                        facts["verified_achievements"] = achievements
                    cur.execute("UPDATE resume_versions SET structured_facts = ?, extracted_text = ? WHERE id = ?", (json.dumps(facts), summary, resume["id"]))

                cur.execute("""
                    INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
                    VALUES (?, 'user', 'web_user', 'profile_updated', 'candidate_profiles', ?, ?)
                """, (f"aud-{uuid.uuid4().hex[:8]}", candidate_id, json.dumps({"name": full_name, "roles": target_roles, "skills": skills})))
                conn.commit()

            self.send_json({
                "success": True,
                "message": "Profil kandidat berhasil diperbarui.",
                "candidate": {
                    "id": candidate_id,
                    "full_name": full_name,
                    "headline": headline,
                    "target_roles": target_roles,
                    "skills": skills,
                    "work_modes": work_modes
                }
            })
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_upload_resume(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            filename = data.get("filename", "resume.pdf").strip()
            content_base64 = data.get("content_base64", "").strip()

            if not content_base64:
                self.send_json({"error": "Konten file resume tidak boleh kosong."}, status=HTTPStatus.BAD_REQUEST)
                return

            if "," in content_base64:
                content_base64 = content_base64.split(",", 1)[1]

            file_bytes = base64.b64decode(content_base64)
            if len(file_bytes) < 100:
                self.send_json({"error": "File PDF tidak valid atau kosong."}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT id, full_name FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                if not cand:
                    self.send_json({"error": "Tidak ada profil kandidat aktif."}, status=HTTPStatus.BAD_REQUEST)
                    return
                candidate_id = cand["id"]

            resumes_dir = ROOT / "uploads" / "resumes"
            resumes_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)
            save_path = resumes_dir / f"{candidate_id}_{safe_name}"
            save_path.write_bytes(file_bytes)

            extracted_text = ""
            try:
                import pypdf
                reader = pypdf.PdfReader(str(save_path))
                extracted_text = "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
            except Exception as e:
                print(f"[PDF Extract Notice] {e}")

            extracted_phone = ""
            phone_match = re.search(r'(\+?62|0)8[1-9][0-9]{7,11}', extracted_text.replace(" ", "").replace("-", ""))
            if phone_match:
                extracted_phone = phone_match.group(0)

            common_skills = [
                "Python", "JavaScript", "TypeScript", "React", "Vue", "Angular", "Node.js", "Express",
                "FastAPI", "Django", "Flask", "Go", "Golang", "Java", "Spring Boot", "PHP", "Laravel",
                "SQL", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Docker", "Kubernetes", "AWS", "GCP",
                "Git", "REST API", "GraphQL", "CI/CD", "Linux", "TailwindCSS", "Figma", "UI/UX",
                "Machine Learning", "Data Analysis", "Pandas", "Scikit-Learn", "TensorFlow", "PyTorch",
                "Product Management", "Digital Marketing", "SEO", "Sales", "Accounting", "Finance"
            ]
            found_skills = [s for s in common_skills if re.search(r'\b' + re.escape(s) + r'\b', extracted_text, re.IGNORECASE)]

            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE resume_versions SET is_current = 0 WHERE candidate_id = ?", (candidate_id,))
                res_id = f"res-{uuid.uuid4().hex[:8]}"
                cur.execute("""
                    INSERT INTO resume_versions (id, candidate_id, version_label, source_uri, extracted_text, structured_facts, content_hash, is_current)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    res_id,
                    candidate_id,
                    safe_name,
                    str(save_path.resolve()),
                    extracted_text or f"Uploaded resume: {safe_name}",
                    json.dumps({
                        "skills": found_skills,
                        "phone": extracted_phone,
                        "filename": safe_name
                    }),
                    uuid.uuid4().hex
                ))
                if extracted_phone:
                    cur.execute("""
                        INSERT INTO system_settings (key, value, updated_at)
                        VALUES ('candidate_phone', ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                    """, (extracted_phone,))
                conn.commit()

            self.send_json({
                "success": True,
                "filename": safe_name,
                "file_path": str(save_path.resolve()),
                "extracted_phone": extracted_phone,
                "extracted_skills": found_skills,
                "message": f"Resume '{safe_name}' berhasil diunggah dan dianalisis."
            })
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_get_cv(self):
        try:
            parsed = urlparse(self.path)
            q_params = parse_qs(parsed.query)
            target_cand_id = q_params.get("candidate_id", [None])[0]

            with get_db() as conn:
                cur = conn.cursor()
                if target_cand_id:
                    cand = cur.execute("SELECT * FROM candidate_profiles WHERE id = ?", (target_cand_id,)).fetchone()
                else:
                    cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY updated_at DESC, created_at DESC LIMIT 1").fetchone()

                if not cand:
                    self.send_json({"error": "Profil kandidat tidak ditemukan."}, status=HTTPStatus.NOT_FOUND)
                    return

                resume = cur.execute("SELECT * FROM resume_versions WHERE candidate_id = ? AND is_current=1 LIMIT 1", (cand["id"],)).fetchone()
                if not resume:
                    resume = cur.execute("SELECT * FROM resume_versions WHERE candidate_id = ? ORDER BY created_at DESC LIMIT 1", (cand["id"],)).fetchone()

            resumes_dir = ROOT / "uploads" / "resumes"
            target_path = None

            # 1. Check exact source_uri from DB for this candidate
            if resume and resume["source_uri"]:
                src_path = Path(resume["source_uri"])
                if src_path.is_file() and src_path.stat().st_size > 500:
                    target_path = src_path

            # 2. Check candidate-specific filename patterns ONLY
            if not target_path and cand["id"]:
                cand_files = sorted(
                    [p for p in resumes_dir.glob(f"{cand['id']}*.pdf") if p.stat().st_size > 500],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                if cand_files:
                    target_path = cand_files[0]

            # 3. If no physical file exists yet for this candidate, generate it automatically
            if not target_path or not target_path.exists() or target_path.stat().st_size < 500:
                target_path = generate_and_save_candidate_cv(cand, resume)

            if not target_path or not target_path.exists() or target_path.stat().st_size < 500:
                self.send_json({"error": "Berkas resume (PDF) untuk profil ini belum tersedia."}, status=HTTPStatus.NOT_FOUND)
                return

            pdf_data = target_path.read_bytes()
            display_name = target_path.name
            if cand["id"] and display_name.startswith(f"{cand['id']}_"):
                display_name = display_name[len(f"{cand['id']}_"):]

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{display_name}"')
            self.send_header("Content-Length", str(len(pdf_data)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(pdf_data)
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"error": f"Gagal membaca berkas CV: {str(exc)}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_parse_job_ai(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            raw_text = data.get("raw_text", "").strip()
            source_url = data.get("url", "https://linkedin.com/jobs").strip()

            if not raw_text:
                self.send_json({"error": "Teks lowongan tidak boleh kosong."}, status=HTTPStatus.BAD_REQUEST)
                return

            prompt = (
                "Ekstrak data lowongan pekerjaan dari teks berikut dalam format JSON murni tanpa markdown/backticks:\n"
                "{\n"
                '  "title": "judul posisi spesifik",\n'
                '  "company": "nama perusahaan",\n'
                '  "location": "lokasi kerja misal Remote, Jakarta, Hybrid",\n'
                '  "skills": ["skill1", "skill2", "skill3"],\n'
                '  "description": "ringkasan deskripsi tugas dan kualifikasi (2-3 kalimat)"\n'
                "}\n\n"
                f"Teks lowongan:\n{raw_text[:3000]}"
            )
            ai_res = call_gemini(prompt)
            title = "Posisi Baru"
            company = "Perusahaan"
            location = "Remote"
            skills = []
            description = raw_text[:300]

            if ai_res:
                try:
                    cleaned = ai_res.strip()
                    if cleaned.startswith("```"):
                        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                    parsed_ai = json.loads(cleaned)
                    title = parsed_ai.get("title", title)
                    company = parsed_ai.get("company", company)
                    location = parsed_ai.get("location", location)
                    skills = parsed_ai.get("skills", [])
                    description = parsed_ai.get("description", description)
                except Exception:
                    pass

            job_id = f"job-{uuid.uuid4().hex[:8]}"
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO jobs (id, source, external_id, url, title, company, location, description, status)
                    VALUES (?, 'ai_parsed_web', ?, ?, ?, ?, ?, ?, 'discovered')
                """, (job_id, job_id, source_url, title, company, location, description))

                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                score = 65
                matched = []
                if cand:
                    resume = cur.execute("SELECT * FROM resume_versions WHERE candidate_id = ? AND is_current=1 LIMIT 1", (cand["id"],)).fetchone()
                    facts = json.loads(resume["structured_facts"]) if resume else {}
                    cand_skills = [s.lower() for s in facts.get("skills", [])]
                    target_roles = json.loads(cand["target_roles"]) if cand["target_roles"] else []
                    preferences = json.loads(cand["preferences"]) if cand["preferences"] else {}
                    preferred_modes = [m.lower() for m in preferences.get("work_modes", ["remote"])]

                    job_text = f"{title} {description}".lower()
                    matched = [s for s in cand_skills if s in job_text]
                    skill_score = min(40, int((len(matched) / max(min(len(cand_skills), 5), 1)) * 40))
                    role_score = 20 if any(r.lower() in title.lower() for r in target_roles) else 0
                    loc_text = f"{location} {description}".lower()
                    loc_score = 15 if any(m in loc_text for m in preferred_modes) else 5
                    domain_score = 15 if ("senior" in title.lower() or "ai" in title.lower()) else 5
                    base_score = 10
                    score = min(100, skill_score + role_score + loc_score + domain_score + base_score)

                    cur.execute("""
                        INSERT OR REPLACE INTO job_matches (id, candidate_id, job_id, score, confidence, evidence, missing_requirements)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        f"jm-{uuid.uuid4().hex[:8]}",
                        cand["id"],
                        job_id,
                        score,
                        "high" if score >= 70 else "medium",
                        json.dumps([{"skill": s, "source": "resume"} for s in matched]),
                        json.dumps([s for s in cand_skills if s not in matched])
                    ))

                cur.execute("""
                    INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
                    VALUES (?, 'agent', 'gemini-3.5-flash-lite', 'job_parsed_ai', 'jobs', ?, ?)
                """, (f"aud-{uuid.uuid4().hex[:8]}", job_id, json.dumps({"title": title, "company": company, "score": score})))
                conn.commit()

            self.send_json({
                "success": True,
                "job": {
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": source_url,
                    "description": description,
                    "skills": skills,
                    "score": score,
                    "matched_skills": matched
                },
                "message": f"Lowongan '{title}' di {company} berhasil diparsing oleh Gemini dan dicocokkan (Skor: {score}%)."
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_update_draft(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            app_id = data.get("application_id")
            cover_letter = data.get("cover_letter", "").strip()

            if not app_id or not cover_letter:
                self.send_json({"error": "application_id dan cover_letter wajib diisi."}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                app = cur.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
                if not app:
                    self.send_json({"error": "Lamaran tidak ditemukan."}, status=HTTPStatus.NOT_FOUND)
                    return

                artifacts = json.loads(app["artifacts"]) if app["artifacts"] else {}
                artifacts["cover_letter"] = cover_letter
                artifacts["last_edited_by"] = "human_reviewer"

                cur.execute("UPDATE applications SET artifacts = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(artifacts), app_id))
                cur.execute("UPDATE approvals SET requested_artifacts = ? WHERE application_id = ?", (json.dumps({"cover_letter": cover_letter}), app_id))

                cur.execute("""
                    INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
                    VALUES (?, 'user', 'human_reviewer', 'cover_letter_edited', 'applications', ?, ?)
                """, (f"aud-{uuid.uuid4().hex[:8]}", app_id, json.dumps({"length": len(cover_letter)})))
                conn.commit()

            self.send_json({
                "success": True,
                "message": "Draf cover letter berhasil disimpan.",
                "cover_letter": cover_letter
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_regenerate_draft(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            app_id = data.get("application_id")
            instructions = data.get("instructions", "").strip()

            if not app_id:
                self.send_json({"error": "application_id diperlukan."}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                row = cur.execute("""
                    SELECT a.id, a.artifacts, j.title as job_title, j.company as job_company, j.description as job_desc,
                           c.full_name, c.headline, r.structured_facts
                    FROM applications a
                    JOIN jobs j ON a.job_id = j.id
                    JOIN candidate_profiles c ON a.candidate_id = c.id
                    LEFT JOIN resume_versions r ON a.resume_version_id = r.id
                    WHERE a.id = ?
                """, (app_id,)).fetchone()

                if not row:
                    self.send_json({"error": "Data lamaran tidak ditemukan."}, status=HTTPStatus.NOT_FOUND)
                    return

                facts = json.loads(row["structured_facts"]) if row["structured_facts"] else {}
                skills = facts.get("skills", ["Python", "FastAPI"])

                prompt = (
                    f"Kamu adalah AI Career Agent profesional. Tulis ulang draf cover letter dalam Bahasa Indonesia "
                    f"untuk posisi {row['job_title']} di {row['job_company']}.\n"
                    f"Profil Kandidat:\n"
                    f"- Nama: {row['full_name']}\n"
                    f"- Headline: {row['headline']}\n"
                    f"- Skill Terverifikasi: {', '.join(skills)}\n\n"
                    f"Target Posisi:\n"
                    f"- Deskripsi: {row['job_desc']}\n\n"
                    f"Instruksi Khusus dari Pengguna:\n"
                    f"{instructions if instructions else 'Buat draf yang lebih padat, tajam, dan persuasif tanpa basa-basi.'}\n\n"
                    f"Aturan mutlak: Jangan gunakan placeholder teks ([...]). Jangan mengarang nama perusahaan fiktif. "
                    f"Langsung tulis teks surat siap kirim."
                )

                new_letter = call_gemini(prompt)
                if not new_letter:
                    new_letter = (
                        f"Yth. Tim Rekrutmen {row['job_company']},\n\n"
                        f"Saya melamar untuk peran {row['job_title']}. Dengan keahlian terverifikasi di bidang {', '.join(skills[:3])}, "
                        f"saya siap memberikan kontribusi langsung pada sasaran teknis tim Anda.\n\n"
                        f"Salam hormat,\n{row['full_name']}"
                    )

                artifacts = json.loads(row["artifacts"]) if row["artifacts"] else {}
                artifacts["cover_letter"] = new_letter
                artifacts["model"] = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

                cur.execute("UPDATE applications SET artifacts = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(artifacts), app_id))
                cur.execute("UPDATE approvals SET requested_artifacts = ? WHERE application_id = ?", (json.dumps({"cover_letter": new_letter}), app_id))

                cur.execute("""
                    INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
                    VALUES (?, 'agent', 'gemini-3.5-flash-lite', 'cover_letter_regenerated', 'applications', ?, ?)
                """, (f"aud-{uuid.uuid4().hex[:8]}", app_id, json.dumps({"instructions": instructions})))
                conn.commit()

            self.send_json({
                "success": True,
                "cover_letter": new_letter,
                "message": "Draf cover letter berhasil digenerate ulang oleh Gemini 3.5 Lite."
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_update_stage(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            app_id = data.get("application_id")
            stage = data.get("stage", "approved").strip()

            valid_stages = ["pending_approval", "approved", "applied", "interviewing", "offered", "rejected"]
            if not app_id or stage not in valid_stages:
                self.send_json({"error": f"Stage tidak valid. Pilihan: {', '.join(valid_stages)}"}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE applications SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (stage, app_id))
                cur.execute("""
                    INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
                    VALUES (?, 'user', 'web_user', 'application_stage_changed', 'applications', ?, ?)
                """, (f"aud-{uuid.uuid4().hex[:8]}", app_id, json.dumps({"stage": stage})))
                conn.commit()

            self.send_json({
                "success": True,
                "application_id": app_id,
                "stage": stage,
                "message": f"Tahap lamaran diubah menjadi: {stage}"
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_copilot_chat(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            user_msg = data.get("message", "").strip()
            history = data.get("history", [])

            if not user_msg:
                self.send_json({"error": "Pesan tidak boleh kosong."}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                cand_info = ""
                if cand:
                    resume = cur.execute("SELECT structured_facts FROM resume_versions WHERE candidate_id = ? LIMIT 1", (cand["id"],)).fetchone()
                    skills = []
                    if resume and resume["structured_facts"]:
                        skills = json.loads(resume["structured_facts"]).get("skills", [])
                    cand_info = f"Nama: {cand['full_name']}, Headline: {cand['headline']}, Target: {cand['target_roles']}, Skill: {', '.join(skills)}"

            system_instruction = (
                "Kamu adalah Career Agent Copilot, asisten AI karier tingkat tinggi berbasis Gemini 3.5 Flash Lite. "
                "Tugasmu membantu kandidat menganalisis strategi karier, membedah lowongan, menyempurnakan CV, "
                "mempersiapkan simulasi interview teknis/HR, dan memberikan rekomendasi taktis nyata. "
                "Gaya bicaramu: Lugas, taktis, profesional, bernas, dan berbobot. "
                "Gunakan Bahasa Indonesia baku yang elegan. "
                "MUTLAK DILARANG MENGGUNAKAN EMOJI DALAM BENTUK APA PUN. "
                f"Konteks Profil Kandidat: {cand_info}"
            )

            conversation_context = ""
            for h in history[-4:]:
                role = "Pengguna" if h.get("role") == "user" else "Copilot"
                conversation_context += f"{role}: {h.get('content', '')}\n"
            full_prompt = f"{conversation_context}Pengguna: {user_msg}\nCopilot:"

            reply = call_gemini(full_prompt, system_instruction=system_instruction)
            if not reply:
                reply = "Sistem Career Agent Copilot sedang memproses analisis. Silakan ajukan pertanyaan seputar karier, review CV, atau persiapan interview Anda."

            self.send_json({
                "success": True,
                "reply": reply,
                "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_diagnostics(self):
        try:
            import time
            start = time.time()
            test_reply = call_gemini("Jawab satu kata: ONLINE")
            latency = int((time.time() - start) * 1000)

            api_configured = bool(os.getenv("GEMINI_API_KEY"))
            self.send_json({
                "status": "online" if test_reply else ("api_unreachable" if api_configured else "no_key"),
                "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                "latency_ms": latency,
                "api_key_configured": api_configured,
                "response_preview": test_reply[:50] if test_reply else "None"
            })
        except Exception as exc:
            self.send_json({"status": "error", "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_keywords_catalog(self):
        try:
            catalog_file = ROOT / "data" / "job_keywords_catalog.json"
            if catalog_file.exists():
                catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
            else:
                catalog = {}
            self.send_json({"success": True, "catalog": catalog})
        except Exception as exc:
            self.send_json({"success": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_scrape_linkedin(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = {}
            if content_length > 0:
                data = json.loads(self.rfile.read(content_length).decode("utf-8"))

            keywords = data.get("keywords", "")
            location = data.get("location", "Indonesia")
            raw_limit = data.get("limit", 6)
            limit = 0 if str(raw_limit).lower() in ("all", "0", "semua") else int(raw_limit)
            easy_apply_only = bool(data.get("easy_apply_only", True))

            result = scrape_and_ingest_linkedin(
                keywords=keywords,
                location=location,
                limit=limit,
                easy_apply_only=easy_apply_only,
                call_gemini_fn=call_gemini
            )
            self.send_json(result)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_import_profile(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = {}
            if content_length > 0:
                data = json.loads(self.rfile.read(content_length).decode("utf-8"))

            url = data.get("url", "").strip()
            if not url:
                self.send_json({"error": "URL profil atau CV online wajib diisi."}, status=HTTPStatus.BAD_REQUEST)
                return

            result = profile_extractor.extract_profile_from_url(url, call_gemini_fn=call_gemini)
            status_code = HTTPStatus.OK if result.get("success") else HTTPStatus.BAD_REQUEST
            self.send_json(result, status=status_code)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_bulk_apply(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = {}
            if content_length > 0:
                data = json.loads(self.rfile.read(content_length).decode("utf-8"))

            job_ids = data.get("job_ids", [])
            if not job_ids or not isinstance(job_ids, list):
                self.send_json({"error": "Daftar job_ids diperlukan."}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                if not cand:
                    self.send_json({"error": "Tidak ada kandidat aktif."}, status=HTTPStatus.BAD_REQUEST)
                    return

                cand_id = cand["id"]
                cand_name = cand["full_name"]
                cand_headline = cand["headline"]
                resume = cur.execute("SELECT id, structured_facts FROM resume_versions WHERE candidate_id = ? AND is_current=1 LIMIT 1", (cand_id,)).fetchone()
                facts = json.loads(resume["structured_facts"]) if resume and resume["structured_facts"] else {}
                skills = facts.get("skills", ["Software Engineer"])
                summary = facts.get("summary", "")

                created_apps = []
                for job_id in job_ids:
                    job = cur.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                    if not job:
                        continue

                    # Check if already has application
                    existing_app = cur.execute("SELECT id, status FROM applications WHERE job_id = ?", (job_id,)).fetchone()
                    if existing_app:
                        created_apps.append({
                            "job_id": job_id,
                            "application_id": existing_app["id"],
                            "status": existing_app["status"],
                            "already_existed": True
                        })
                        continue

                    # Calculate match score if not present
                    existing_match = cur.execute("SELECT score FROM job_matches WHERE job_id = ?", (job_id,)).fetchone()
                    score = existing_match["score"] if existing_match else 65

                    # Draft cover letter with Gemini
                    title = job["title"]
                    company = job["company"]
                    desc = job["description"] or ""
                    prompt = (
                        f"Kamu adalah AI Career Agent profesional. Buat surat lamaran kerja resmi Bahasa Indonesia (2 paragraf ringkas, persuasif, tanpa placeholder [...], tanpa emoji) untuk posisi berikut:\n"
                        f"Posisi: {title}\n"
                        f"Perusahaan: {company}\n"
                        f"Deskripsi Ringkas: {desc[:600]}\n"
                        f"Kandidat: {cand_name} ({cand_headline})\n"
                        f"Keahlian Utama: {', '.join(skills[:6])}\n"
                        f"Ringkasan: {summary[:300]}\n"
                    )
                    ai_letter = call_gemini(prompt)
                    if not ai_letter:
                        ai_letter = (
                            f"Yth. Tim Rekrutmen {company},\n\n"
                            f"Saya tertarik untuk mengajukan lamaran peran {title}. Dengan latar belakang sebagai {cand_headline} "
                            f"dan penguasaan teknis di bidang {', '.join(skills[:3])}, saya yakin dapat memberikan kontribusi nyata bagi tim Anda.\n\n"
                            f"Salam hormat,\n{cand_name}"
                        )

                    app_id = f"app-{uuid.uuid4().hex[:8]}"
                    cur.execute("""
                        INSERT INTO applications (id, candidate_id, job_id, resume_version_id, status, artifacts, notes)
                        VALUES (?, ?, ?, ?, 'pending_approval', ?, ?)
                    """, (
                        app_id,
                        cand_id,
                        job_id,
                        resume["id"] if resume else None,
                        json.dumps({
                            "cover_letter": ai_letter,
                            "matched_skills": skills[:4],
                            "score": score,
                            "model": "gemini-3.5-flash-lite",
                            "source": "bulk_apply"
                        }),
                        f"Diajukan sekaligus via Bulk Apply. Skor kecocokan: {score}%"
                    ))

                    cur.execute("""
                        INSERT OR REPLACE INTO approvals (id, application_id, status, requested_artifacts, reviewer)
                        VALUES (?, ?, 'pending', ?, 'Aditya')
                    """, (f"appr-{uuid.uuid4().hex[:8]}", app_id, json.dumps({"cover_letter": ai_letter})))

                    created_apps.append({
                        "job_id": job_id,
                        "application_id": app_id,
                        "title": title,
                        "company": company,
                        "status": "pending_approval",
                        "score": score
                    })

                cur.execute("""
                    INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
                    VALUES (?, 'user', 'web_user', 'bulk_apply_executed', 'applications', ?, ?)
                """, (
                    f"aud-{uuid.uuid4().hex[:8]}",
                    cand_id,
                    json.dumps({"total_selected": len(job_ids), "created": len(created_apps)})
                ))
                conn.commit()

            self.send_json({
                "success": True,
                "count": len(created_apps),
                "items": created_apps,
                "message": f"Berhasil mengajukan {len(created_apps)} lowongan sekaligus ke Inbox Persetujuan!"
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_auto_chain(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = {}
            if content_length > 0:
                data = json.loads(self.rfile.read(content_length).decode("utf-8"))

            url = data.get("url", "").strip()
            if url:
                profile_res = profile_extractor.extract_profile_from_url(url, call_gemini_fn=call_gemini)
                if not profile_res.get("success"):
                    self.send_json(profile_res, status=HTTPStatus.BAD_REQUEST)
                    return

            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                if not cand:
                    self.send_json({"error": "Profil kandidat belum tersedia."}, status=HTTPStatus.BAD_REQUEST)
                    return
                target_roles = json.loads(cand["target_roles"]) if cand["target_roles"] else ["Backend Developer"]
                cand_name = cand["full_name"]

            search_keyword = (data.get("keywords") or "").strip() or (target_roles[0] if target_roles else "Software Engineer")
            search_location = (data.get("location") or "").strip() or "Indonesia"
            limit_num = int(data.get("limit") or 6)
            easy_only = bool(data.get("easy_apply_only", True))

            scrape_res = scrape_and_ingest_linkedin(
                keywords=search_keyword,
                location=search_location,
                limit=limit_num,
                easy_apply_only=easy_only,
                call_gemini_fn=call_gemini
            )

            self.send_json({
                "success": True,
                "candidate_name": cand_name,
                "search_keyword": search_keyword,
                "scraped_jobs_count": scrape_res.get("ingested_count", 0),
                "drafts_created": scrape_res.get("drafts_created", 0),
                "message": f"Berhasil memindai lowongan Easy Apply untuk '{search_keyword}' di {search_location}."
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_get_credentials(self):
        try:
            li_at = linkedin_easy_apply.get_stored_li_at()
            phone = linkedin_easy_apply.get_stored_phone()
            self.send_json({
                "linkedin_configured": bool(li_at),
                "li_at_preview": f"{li_at[:6]}...{li_at[-4:]}" if li_at and len(li_at) > 10 else "",
                "phone": phone
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_save_credentials(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
            li_at = data.get("li_at", "").strip()
            phone = data.get("phone", "").strip()

            if li_at or phone:
                current_li_at = li_at if li_at else linkedin_easy_apply.get_stored_li_at()
                current_phone = phone if (phone and phone != "0" and len(phone) >= 8) else linkedin_easy_apply.get_stored_phone()
                linkedin_easy_apply.save_stored_li_at(current_li_at, current_phone)

            self.send_json({
                "success": True,
                "message": "Kredensial sesi LinkedIn dan nomor kontak berhasil disimpan."
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_verify_linkedin_session(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
            li_at = data.get("li_at", "").strip() or linkedin_easy_apply.get_stored_li_at()

            if not li_at:
                self.send_json({"valid": False, "error": "Cookie li_at belum dimasukkan."}, status=HTTPStatus.BAD_REQUEST)
                return

            result = linkedin_easy_apply.verify_linkedin_session(li_at, headless=True)
            status_code = HTTPStatus.OK if result.get("valid") else HTTPStatus.UNAUTHORIZED
            self.send_json(result, status=status_code)
        except Exception as exc:
            self.send_json({"valid": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_sync_linkedin_profile(self):
        try:
            li_at = linkedin_easy_apply.get_stored_li_at()
            if not li_at:
                self.send_json({"success": False, "error": "Cookie li_at LinkedIn belum dikonfigurasi."}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                profile_url = cand["external_key"] if cand and cand["external_key"] else ""

            res = linkedin_easy_apply.sync_linkedin_profile_and_resume(
                li_at_cookie=li_at,
                profile_url=profile_url,
                headless=True,
                call_gemini_fn=call_gemini
            )
            self.send_json(res)
        except Exception as exc:
            self.send_json({"success": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_chrome_sync(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
            cdp_url = data.get("cdp_url", "http://127.0.0.1:9222")

            res = linkedin_easy_apply.extract_from_live_chrome(cdp_url)
            self.send_json(res)
        except Exception as exc:
            self.send_json({"success": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_dom_sync(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
            html = data.get("html", "")
            if not html:
                self.send_json({"success": False, "error": "HTML content tidak boleh kosong."}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                phone = cur.execute("SELECT value FROM system_settings WHERE key='candidate_phone'").fetchone()
                resume = None
                if cand:
                    resume = cur.execute("SELECT * FROM resume_versions WHERE candidate_id = ? AND is_current = 1 LIMIT 1", (cand["id"],)).fetchone()

            target_roles = []
            if cand and cand["target_roles"]:
                try: target_roles = json.loads(cand["target_roles"])
                except Exception: pass

            preferences = {}
            if cand and cand["preferences"]:
                try: preferences = json.loads(cand["preferences"])
                except Exception: pass

            facts = {}
            if resume and resume["structured_facts"]:
                try: facts = json.loads(resume["structured_facts"])
                except Exception: pass

            exp_years = preferences.get("experience_years", 3)
            expected_sal = preferences.get("expected_salary", 10000000)

            candidate_context = {
                "name": cand["full_name"] if cand else "Pelamar Kerja",
                "phone": phone[0] if phone else "",
                "headline": cand["headline"] if cand and cand["headline"] else "Profesional",
                "location": cand["location"] if cand and cand["location"] else "Indonesia",
                "skills": facts.get("skills", ["Komunikasi", "Problem Solving"]),
                "target_roles": target_roles or ["Software Engineer"],
                "experience_summary": facts.get("summary") or f"{exp_years}+ tahun pengalaman profesional.",
                "experience_years": exp_years,
                "education": facts.get("education", "Pendidikan Tinggi / Sarjana"),
                "salary_expectation": str(expected_sal),
                "salary_currency": "IDR",
                "notice_period": "Segera / Immediate",
                "work_authorization": "WNI / Citizen",
                "visa_sponsorship": "Tidak / No"
            }

            parsed = linkedin_easy_apply.parse_easy_apply_dom(
                html_content=html,
                candidate_context=candidate_context,
                call_gemini_fn=call_gemini
            )
            self.send_json(parsed)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.send_json({"success": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_easy_apply(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
            job_id = data.get("job_id")
            app_id = data.get("application_id")
            dry_run = data.get("dry_run", True)

            li_at = linkedin_easy_apply.get_stored_li_at()
            if not li_at:
                self.send_json({
                    "success": False,
                    "error": "Cookie sesi LinkedIn (li_at) belum dikonfigurasi. Masukkan cookie sesi Anda di tab Profil & CV."
                }, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                if not job_id and app_id:
                    app_row = cur.execute("SELECT job_id FROM applications WHERE id = ?", (app_id,)).fetchone()
                    if app_row:
                        job_id = app_row["job_id"]

                job = cur.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                if not job:
                    self.send_json({"success": False, "error": "Lowongan tidak ditemukan."}, status=HTTPStatus.NOT_FOUND)
                    return
                job_data = dict(job)

                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                cand_data = dict(cand) if cand else {"full_name": "Pelamar Kerja"}
                cand_data["phone"] = linkedin_easy_apply.get_stored_phone()

                # Enrich with resume path and facts
                resume_file = ""
                res_row = cur.execute("SELECT source_uri, structured_facts FROM resume_versions WHERE candidate_id = ? ORDER BY is_current DESC, created_at DESC LIMIT 1", (cand_data.get("id", ""),)).fetchone()
                if res_row:
                    if res_row[0] and Path(res_row[0]).exists():
                        resume_file = res_row[0]
                    if res_row[1]:
                        try:
                            facts = json.loads(res_row[1])
                            cand_data["skills"] = facts.get("skills", [])
                            cand_data["structured_facts"] = facts.get("summary", "") or json.dumps(facts.get("verified_achievements", []))
                        except Exception:
                            pass
                if not resume_file and cand_data.get("id"):
                    pdf_fallback = ROOT / "uploads" / "resumes" / f"{cand_data.get('id')}_Profile.pdf"
                    if pdf_fallback.exists():
                        resume_file = str(pdf_fallback)

            # Check if this is an external ATS (Ashby, Greenhouse, Lever, etc.)
            job_target_url = job_data.get("url", "")
            is_external_ats = any(ats in job_target_url.lower() for ats in ("ashbyhq.com", "greenhouse.io", "lever.co", "workable.com"))

            if is_external_ats:
                ext_result = external_apply.apply_external_job(
                    job_url=job_target_url,
                    candidate_data=cand_data,
                    resume_path=resume_file,
                    dry_run=dry_run,
                    call_gemini_fn=call_gemini
                )
                result = {
                    "success": ext_result.get("success", False),
                    "status": "submitted" if ext_result.get("submitted") else "ready_for_submit",
                    "screenshot": ext_result.get("screenshot_url", ""),
                    "actions": ext_result.get("actions", []),
                    "platform": ext_result.get("platform", "External ATS")
                }
            else:
                # Execute Easy Apply Automation via Playwright with Gemini AI assistance
                result = linkedin_easy_apply.apply_easy_apply(
                    job_url=job_target_url,
                    candidate_data=cand_data,
                    li_at_cookie=li_at,
                    dry_run=dry_run,
                    headless=True,
                    call_gemini_fn=call_gemini
                )

            # Update DB application status and artifacts
            screenshot_path = result.get("screenshot", "")
            res_status = result.get("status", "")
            import datetime
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with get_db() as conn:
                cur = conn.cursor()
                app_row = cur.execute("SELECT id, artifacts, notes FROM applications WHERE job_id = ?", (job_id,)).fetchone()
                
                new_status = None
                if res_status == "submitted":
                    new_status = "applied"
                elif res_status == "ready_for_submit":
                    new_status = "dry_run_ready"
                elif res_status == "external_apply_only":
                    new_status = "external"

                if app_row:
                    try:
                        arts = json.loads(app_row["artifacts"]) if app_row["artifacts"] else {}
                    except Exception:
                        arts = {}
                    if screenshot_path:
                        arts["screenshot"] = screenshot_path
                    arts["last_result"] = result
                    
                    cur.execute("""
                        UPDATE applications 
                        SET status = COALESCE(?, status), artifacts = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (new_status, json.dumps(arts), app_row["id"]))
                else:
                    app_id = f"app-{uuid.uuid4().hex[:8]}"
                    arts = {"screenshot": screenshot_path, "last_result": result}
                    cur.execute("""
                        INSERT INTO applications (id, candidate_id, job_id, status, artifacts, notes)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        app_id,
                        cand_data.get("id"),
                        job_id,
                        new_status or "applied",
                        json.dumps(arts),
                        f"Dilamar via Autonomous Agent ({result.get('platform', 'Easy Apply')}) pada {now_str}"
                    ))

                cur.execute("""
                    INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
                    VALUES (?, 'bot', 'autonomous_apply_bot', 'application_executed', 'applications', ?, ?)
                """, (f"aud-{uuid.uuid4().hex[:8]}", job_id, json.dumps(result)))
                conn.commit()

            self.send_json(result)
        except Exception as exc:
            self.send_json({"success": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_external_apply(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
            job_url = data.get("url", "").strip()
            dry_run = bool(data.get("dry_run", True))

            if not job_url:
                self.send_json({"success": False, "error": "URL lowongan external wajib diisi."}, status=HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.cursor()
                cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
                cand_data = dict(cand) if cand else {"full_name": "Pelamar Kerja", "email": "pelamar@example.com"}
                cand_data["phone"] = linkedin_easy_apply.get_stored_phone() or "+6281399887766"

                res_row = cur.execute("SELECT source_uri, structured_facts FROM resume_versions WHERE candidate_id = ? ORDER BY is_current DESC, created_at DESC LIMIT 1", (cand_data.get("id", ""),)).fetchone()
                resume_path = ""
                if res_row and res_row[0] and Path(res_row[0]).exists():
                    resume_path = res_row[0]
                    try:
                        facts = json.loads(res_row[1]) if res_row[1] else {}
                        cand_data["skills"] = facts.get("skills", [])
                        cand_data["structured_facts"] = facts.get("summary", "")
                    except Exception:
                        pass
                elif cand_data.get("id"):
                    pdf_fallback = ROOT / "uploads" / "resumes" / f"{cand_data.get('id')}_Profile.pdf"
                    if pdf_fallback.exists():
                        resume_path = str(pdf_fallback)

            result = external_apply.apply_external_job(
                job_url=job_url,
                candidate_data=cand_data,
                resume_path=resume_path,
                dry_run=dry_run,
                call_gemini_fn=call_gemini
            )
            self.send_json(result)
        except Exception as exc:
            self.send_json({"success": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_start_manual_login(self):
        global manual_login_state
        import time

        if manual_login_state.get("status") == "in_progress":
            self.send_json({
                "success": True,
                "status": "in_progress",
                "message": "Jendela login browser sudah dibuka di layar Anda. Silakan masukkan akun LinkedIn Anda."
            })
            return

        def run_manual_login():
            global manual_login_state
            manual_login_state["status"] = "in_progress"
            manual_login_state["message"] = "Membuka jendela konsol dan peramban Chromium di layar..."
            manual_login_state["updated_at"] = time.time()
            manual_login_state["result"] = None

            initial_cookie = linkedin_easy_apply.get_stored_li_at()
            start_time = time.time()
            task_name = "CareerAgent_ManualLogin"
            launched_interactive = False
            proc = None

            try:
                bat_file = ROOT / "buka_login_linkedin.bat"
                if sys.platform == "win32":
                    try:
                        tr_cmd = str(bat_file)
                        create_res = subprocess.run(
                            ["schtasks", "/create", "/tn", task_name, "/tr", tr_cmd, "/sc", "once", "/st", "23:59", "/f", "/it"],
                            capture_output=True, timeout=5
                        )
                        if create_res.returncode == 0:
                            run_res = subprocess.run(["schtasks", "/run", "/tn", task_name], capture_output=True, timeout=5)
                            if run_res.returncode == 0:
                                launched_interactive = True
                    except Exception:
                        pass

                if not launched_interactive:
                    creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform == "win32" else 0
                    proc = subprocess.Popen(
                        [sys.executable, str(ROOT / "linkedin_manual_login.py"), "--fresh"],
                        cwd=str(ROOT),
                        creationflags=creation_flags
                    )

                while time.time() - start_time < 300:
                    if proc and proc.poll() is not None:
                        break

                    current_cookie = linkedin_easy_apply.get_stored_li_at()
                    if current_cookie and current_cookie != initial_cookie and len(current_cookie) > 20:
                        time.sleep(2.5)
                        break

                    time.sleep(1.0)

                new_cookie = linkedin_easy_apply.get_stored_li_at()
                if new_cookie and len(new_cookie) > 20 and (not initial_cookie or new_cookie != initial_cookie or (proc and proc.poll() == 0)):
                    manual_login_state["status"] = "completed"
                    manual_login_state["message"] = "Login LinkedIn berhasil diverifikasi! Profil telah disinkronkan ke Dashboard."
                    manual_login_state["result"] = {"success": True, "status": "completed"}
                else:
                    manual_login_state["status"] = "timeout"
                    manual_login_state["message"] = "Login belum diselesaikan atau peramban ditutup."
            except Exception as e:
                manual_login_state["status"] = "error"
                manual_login_state["message"] = f"Kendala peramban: {str(e)}"
            finally:
                if sys.platform == "win32" and launched_interactive:
                    try:
                        subprocess.run(["schtasks", "/delete", "/tn", task_name, "/f"], capture_output=True, timeout=5)
                    except Exception:
                        pass
                manual_login_state["updated_at"] = time.time()

        t = threading.Thread(target=run_manual_login, daemon=True)
        t.start()

        self.send_json({
            "success": True,
            "status": "launched",
            "message": "Browser Chromium telah dibuka di layar Anda. Silakan login ke akun LinkedIn Anda."
        })

    def handle_api_cancel_manual_login(self):
        global manual_login_state
        import time
        if sys.platform == "win32":
            try:
                subprocess.run(["schtasks", "/delete", "/tn", "CareerAgent_ManualLogin", "/f"], capture_output=True, timeout=5)
            except Exception:
                pass
        linkedin_manual_login.cleanup_stale_playwright_processes()
        manual_login_state["status"] = "idle"
        manual_login_state["message"] = "Login dibatalkan."
        manual_login_state["updated_at"] = time.time()
        manual_login_state["result"] = None
        self.send_json({"success": True, "message": "Proses login telah dibatalkan."})

    def handle_api_auth_login(self):
        global manual_login_state
        import time

        content_length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()

        if not email or not password:
            self.send_json({"error": "Email dan password LinkedIn wajib diisi."}, status=HTTPStatus.BAD_REQUEST)
            return

        if manual_login_state.get("status") == "in_progress":
            self.send_json({
                "success": True,
                "status": "in_progress",
                "message": "Otentikasi sedang berjalan di peramban. Silakan periksa jendela yang terbuka di layar."
            })
            return

        def run_auth():
            global manual_login_state
            manual_login_state["status"] = "in_progress"
            manual_login_state["message"] = "Meluncurkan peramban dan mengisi data login..."
            manual_login_state["updated_at"] = time.time()
            manual_login_state["result"] = None

            def on_status(status_code, msg):
                manual_login_state["message"] = msg
                manual_login_state["updated_at"] = time.time()

            try:
                res = linkedin_manual_login.login_with_credentials(
                    email=email,
                    password=password,
                    timeout_seconds=180,
                    on_status_update=on_status
                )
                manual_login_state["status"] = res.get("status", "completed")
                manual_login_state["message"] = res.get("message") or res.get("error", "Selesai")
                manual_login_state["result"] = res
                manual_login_state["updated_at"] = time.time()
            except Exception as e:
                manual_login_state["status"] = "error"
                manual_login_state["message"] = f"Kendala peramban: {str(e)}"
                manual_login_state["updated_at"] = time.time()

        t = threading.Thread(target=run_auth, daemon=True)
        t.start()

        self.send_json({
            "success": True,
            "status": "launched",
            "message": "Proses login LinkedIn dimulai. Peramban telah dibuka di layar Anda."
        })

    def handle_api_linkedin_disconnect(self):
        try:
            global manual_login_state
            manual_login_state["status"] = "idle"
            manual_login_state["message"] = "Akun LinkedIn berhasil diputuskan."
            manual_login_state["result"] = None

            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM system_settings WHERE key = 'linkedin_li_at'")
                cand = cur.execute("SELECT id, preferences FROM candidate_profiles WHERE active = 1").fetchone()
                if cand:
                    prefs = {}
                    if cand[1]:
                        try:
                            prefs = json.loads(cand[1])
                            prefs.pop("avatar_url", None)
                        except Exception:
                            prefs = {}
                    cur.execute("UPDATE candidate_profiles SET external_key = '', preferences = ? WHERE id = ?", (json.dumps(prefs), cand[0]))
                conn.commit()

            cookies_file = ROOT / "data" / "linkedin_cookies.json"
            if cookies_file.exists():
                try:
                    cookies_file.unlink()
                except Exception:
                    pass

            # Bersihkan sesi peramban secara tuntas agar akun lama logout sempurna
            linkedin_manual_login.clean_browser_profile()

            self.send_json({
                "success": True,
                "message": "Akun LinkedIn berhasil diputuskan dan sesi peramban telah dibersihkan. Anda dapat login ke akun LinkedIn baru."
            })
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_sync_linkedin_profile(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
            li_at = data.get("li_at", "").strip() or linkedin_easy_apply.get_stored_li_at()
            if not li_at:
                self.send_json({"error": "Sesi LinkedIn (li_at) belum tersimpan."}, status=HTTPStatus.BAD_REQUEST)
                return

            res = linkedin_manual_login.sync_profile_with_cookie(li_at)
            if res.get("success"):
                self.send_json(res)
            else:
                self.send_json(res, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)


def run_server(port=None):
    if port is None:
        if len(sys.argv) > 1 and sys.argv[1].isdigit():
            port = int(sys.argv[1])
        else:
            try:
                port = int(os.environ.get("PORT", "3000"))
            except ValueError:
                port = 3000

    server = None
    candidate_ports = [port] + [p for p in [3001, 3002, 3003, 8080] if p != port]
    for p in candidate_ports:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), CareerHandler)
            port = p
            break
        except OSError as e:
            print(f"[Notice] Port {p} tidak dapat digunakan ({e}), mencoba port berikutnya...")

    if server is None:
        raise RuntimeError("Gagal mengikat port untuk Career Agent.")

    print(f"Career Agent server running at http://localhost:{port}")
    print(f"Landing Page: http://localhost:{port}/")
    print(f"Dashboard: http://localhost:{port}/dashboard")
    server.serve_forever()


if __name__ == "__main__":
    run_server()

