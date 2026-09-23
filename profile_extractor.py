"""Profile & CV Extractor for Career Agent.

Automatically extracts professional profile & CV facts from links (LinkedIn, GitHub,
personal portfolio, or web CV) and structures them using Gemini 3.5 Flash Lite.
Direct extraction without third-party proxy/actor services.
"""

import html
import json
import os
import re
import sqlite3
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database" / "career_agent.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def clean_html_text(raw_html: str) -> str:
    """Strips script, style, tags, and collapses whitespaces."""
    text = re.sub(r'<script.*?</script>', ' ', raw_html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<style.*?</style>', ' ', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<noscript.*?</noscript>', ' ', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def fetch_url_content(url: str, timeout: int = 15) -> tuple:
    """Fetches URL and returns (html_content, metadata_dict).
    Uses bot/crawler User-Agents rotation for LinkedIn to bypass anti-scraping HTTP 999.
    """
    user_agents = [
        # 1. Social preview bot (LinkedIn permits these without HTTP 999)
        'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
        'Twitterbot/1.0',
        'WhatsApp/2.21.12.21 i',
        # 2. Desktop Chrome
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    ]

    raw = ""
    last_error = None

    for ua in user_agents:
        try:
            headers = {
                'User-Agent': ua,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,id;q=0.8',
                'Cache-Control': 'no-cache',
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                raw = res.read().decode('utf-8', errors='ignore')
                if raw and len(raw) > 500:
                    break
        except Exception as exc:
            last_error = exc
            continue

    if not raw:
        raise last_error or Exception("Gagal mengunduh halaman dari URL.")

    # Extract Meta & OpenGraph
    title_m = re.search(r'<title>(.*?)</title>', raw, re.IGNORECASE | re.DOTALL)
    title = html.unescape(title_m.group(1).strip()) if title_m else ""

    og_title_m = re.search(r'<meta\s+(?:property|name)=["\']og:title["\']\s+content=["\'](.*?)["\']', raw, re.IGNORECASE)
    og_title = html.unescape(og_title_m.group(1).strip()) if og_title_m else ""

    og_desc_m = re.search(r'<meta\s+(?:property|name)=["\']og:description["\']\s+content=["\'](.*?)["\']', raw, re.IGNORECASE)
    og_desc = html.unescape(og_desc_m.group(1).strip()) if og_desc_m else ""

    meta_desc_m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', raw, re.IGNORECASE)
    meta_desc = html.unescape(meta_desc_m.group(1).strip()) if meta_desc_m else ""

    json_lds = re.findall(r'<script\s+type=["\']application/ld\+json["\']>(.*?)</script>', raw, re.IGNORECASE | re.DOTALL)

    return raw, {
        "title": title,
        "og_title": og_title,
        "og_desc": og_desc,
        "meta_desc": meta_desc,
        "json_lds": [j.strip() for j in json_lds if j.strip()][:3],
        "body_text": clean_html_text(raw)[:6000]
    }


def fetch_github_profile(username: str) -> dict:
    """Fetches GitHub public profile & recent repository languages via GitHub API."""
    headers = {
        'User-Agent': 'CareerAgent',
        'Accept': 'application/vnd.github.v3+json'
    }
    profile_data = {}
    try:
        user_url = f"https://api.github.com/users/{username}"
        req = urllib.request.Request(user_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as res:
            profile_data = json.loads(res.read().decode('utf-8'))
    except Exception:
        pass

    repos_data = []
    try:
        repos_url = f"https://api.github.com/users/{username}/repos?sort=updated&per_page=8"
        req = urllib.request.Request(repos_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as res:
            repos_data = json.loads(res.read().decode('utf-8'))
    except Exception:
        pass

    return {
        "user": profile_data,
        "repos": [
            {
                "name": r.get("name"),
                "description": r.get("description"),
                "language": r.get("language"),
                "stars": r.get("stargazers_count")
            } for r in repos_data if isinstance(r, dict)
        ]
    }


def extract_profile_from_url(url: str, call_gemini_fn) -> dict:
    """Extracts candidate profile facts from URL, structures via Gemini, and saves to database."""
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    # 1. Gather raw context depending on domain
    context_text = f"Target URL: {url}\n\n"
    gh_match = re.search(r'github\.com/([a-zA-Z0-9\-_]+)/?$', url)

    if gh_match:
        username = gh_match.group(1)
        gh_info = fetch_github_profile(username)
        u = gh_info.get("user", {})
        context_text += (
            f"GitHub User: {username}\n"
            f"Name: {u.get('name') or username}\n"
            f"Bio: {u.get('bio') or ''}\n"
            f"Company: {u.get('company') or ''}\n"
            f"Location: {u.get('location') or ''}\n"
            f"Blog / Website: {u.get('blog') or ''}\n"
            f"Repositories & Skills: {json.dumps(gh_info.get('repos', []))}\n"
        )
    else:
        try:
            _, meta = fetch_url_content(url)
            context_text += (
                f"Page Title: {meta['title']}\n"
                f"OG Title: {meta['og_title']}\n"
                f"OG Description: {meta['og_desc']}\n"
                f"Meta Description: {meta['meta_desc']}\n"
            )
            if meta['json_lds']:
                context_text += f"Structured Data: {' '.join(meta['json_lds'])[:1500]}\n"
            context_text += f"Extracted Page Content:\n{meta['body_text']}\n"
        except Exception as exc:
            return {"success": False, "error": f"Gagal mengakses URL ({exc}). Pastikan URL publik dan dapat diakses."}

    # 2. Structure via Gemini 3.5 Flash Lite
    prompt = (
        "Kamu adalah AI Ekstraktor Profil Profesional & CV. Analisis teks dan metadata berikut yang diambil dari URL profil kandidat:\n\n"
        f"{context_text[:5000]}\n\n"
        "Tugasmu: Ekstrak dan simpulkan data profesional kandidat ke dalam format JSON murni dengan skema berikut:\n"
        "{\n"
        '  "full_name": "Nama Lengkap Kandidat",\n'
        '  "headline": "Headline profesional (contoh: Senior Backend & Cloud Engineer)",\n'
        '  "target_roles": ["Role 1", "Role 2", "Role 3"],\n'
        '  "work_modes": ["remote", "hybrid"],\n'
        '  "skills": ["Skill 1", "Skill 2", "Skill 3", "Skill 4", "Skill 5", "Skill 6"],\n'
        '  "summary": "Ringkasan profil profesional 2-3 kalimat yang menjual dan berbasis fakta yang terdeteksi.",\n'
        '  "achievements": [\n'
        '    "Peran di Perusahaan (Tahun) - Keterangan pencapaian singkat",\n'
        '    "Proyek atau kontribusi kunci"\n'
        '  ]\n'
        "}\n\n"
        "Aturan Mutlak:\n"
        "1. Berikan HANYA JSON valid tanpa teks pengantar atau penutup.\n"
        "2. Jika nama lengkap tidak tertulis jelas, gunakan nama dari title atau username URL.\n"
        "3. Jangan gunakan tanda placeholder teks seperti '[...]' atau 'N/A'.\n"
        "4. Dilarang menggunakan emoji apa pun di seluruh nilai string.\n"
        "5. Jika pengalaman spesifik minim, rumuskan ringkasan berbasis keahlian teknis yang tertera."
    )

    gemini_raw = call_gemini_fn(prompt)
    if not gemini_raw:
        return {"success": False, "error": "Model AI tidak mengembalikan respons ekstraksi profil."}

    # Parse JSON
    try:
        cleaned = re.sub(r'^```json\s*', '', gemini_raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r'```$', '', cleaned.strip())
        profile_dict = json.loads(cleaned)
    except Exception:
        # Fallback regex extraction
        json_match = re.search(r'\{.*\}', gemini_raw, re.DOTALL)
        if json_match:
            try:
                profile_dict = json.loads(json_match.group(0))
            except Exception as e:
                return {"success": False, "error": f"Gagal mem-parsing format respons AI: {e}"}
        else:
            return {"success": False, "error": "AI tidak mengembalikan JSON yang valid."}

    full_name = profile_dict.get("full_name", "").strip()
    if not full_name or full_name.lower().startswith("candidate"):
        if url:
            try:
                from urllib.parse import urlparse
                parts = urlparse(url).path.strip("/").split("/")
                if len(parts) >= 2 and parts[0] == "in":
                    slug = re.sub(r"-[0-9a-fA-F]{6,}$", "", parts[1])
                    slug = re.sub(r"-\d+$", "", slug)
                    cleaned = slug.replace("-", " ").title().strip()
                    if cleaned:
                        full_name = cleaned
            except Exception:
                pass
    if not full_name or full_name.lower().startswith("candidate"):
        try:
            with get_db() as conn:
                cur = conn.cursor()
                row = cur.execute("SELECT full_name FROM candidate_profiles WHERE active=1 AND full_name NOT LIKE 'Candidate%' AND full_name NOT LIKE 'Kandidat%' LIMIT 1").fetchone()
                full_name = (row and row[0]) or "Kandidat Pelamar"
        except Exception:
            full_name = "Kandidat Pelamar"

    headline = profile_dict.get("headline", "Software Engineer").strip()
    target_roles = profile_dict.get("target_roles", ["Backend Engineer", "Software Engineer"])
    if isinstance(target_roles, str):
        target_roles = [r.strip() for r in target_roles.split(",") if r.strip()]
    work_modes = profile_dict.get("work_modes", ["remote", "hybrid"])
    if isinstance(work_modes, str):
        work_modes = [m.strip() for m in work_modes.split(",") if m.strip()]

    skills = profile_dict.get("skills", ["Python", "Git", "SQL"])
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]

    summary = profile_dict.get("summary", "").strip()
    achievements = profile_dict.get("achievements", [])
    if isinstance(achievements, str):
        achievements = [a.strip() for a in achievements.split("\n") if a.strip()]

    # 3. Update active candidate in SQLite database
    candidate_id = None
    with get_db() as conn:
        cur = conn.cursor()
        cand = cur.execute("SELECT id FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
        if cand:
            candidate_id = cand["id"]
        else:
            candidate_id = f"cand-{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO candidate_profiles (id, external_key, full_name, headline, target_roles, preferences, consent, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                candidate_id,
                url,
                full_name,
                headline,
                json.dumps(target_roles),
                json.dumps({"work_modes": work_modes}),
                json.dumps({"require_human_approval": True, "auto_submit": False})
            ))

        cur.execute("""
            UPDATE candidate_profiles
            SET full_name = ?, headline = ?, target_roles = ?, preferences = ?, external_key = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            full_name,
            headline,
            json.dumps(target_roles),
            json.dumps({"work_modes": work_modes}),
            url,
            candidate_id
        ))

        # Update Resume structured facts
        resume = cur.execute("SELECT id FROM resume_versions WHERE candidate_id = ? AND is_current=1 LIMIT 1", (candidate_id,)).fetchone()
        facts_payload = json.dumps({
            "skills": skills,
            "verified_achievements": achievements,
            "summary": summary,
            "source_url": url
        })

        if resume:
            cur.execute("""
                UPDATE resume_versions
                SET structured_facts = ?, extracted_text = ?, source_uri = ?
                WHERE id = ?
            """, (facts_payload, summary, url, resume["id"]))
        else:
            cur.execute("""
                INSERT INTO resume_versions (id, candidate_id, version_label, source_uri, extracted_text, structured_facts, content_hash, is_current)
                VALUES (?, ?, 'url-import', ?, ?, ?, ?, 1)
            """, (
                f"res-{uuid.uuid4().hex[:8]}",
                candidate_id,
                url,
                summary,
                facts_payload,
                f"hash-{uuid.uuid4().hex[:8]}"
            ))

        # Audit Event
        cur.execute("""
            INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
            VALUES (?, 'ai_agent', 'gemini-3.5-flash-lite', 'profile_auto_imported_from_url', 'candidate_profiles', ?, ?)
        """, (
            f"aud-{uuid.uuid4().hex[:8]}",
            candidate_id,
            json.dumps({"url": url, "full_name": full_name, "skills_count": len(skills)})
        ))
        conn.commit()

    return {
        "success": True,
        "candidate_id": candidate_id,
        "url": url,
        "profile": {
            "full_name": full_name,
            "headline": headline,
            "target_roles": ", ".join(target_roles),
            "work_modes": ", ".join(work_modes),
            "skills": ", ".join(skills),
            "summary": summary,
            "achievements": "\n".join(achievements)
        },
        "message": f"Profil {full_name} berhasil diekstrak dan diisi secara otomatis dari {url}."
    }
