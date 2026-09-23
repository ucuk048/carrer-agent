"""LinkedIn Jobs Automated Scraper & Ingestion Engine for Career Agent.

Uses LinkedIn Public Guest API to fetch live job listings and detailed descriptions
without requiring login credentials or third-party paid services.
100% Python Standard Library (no external dependencies required).
"""

import html
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database" / "career_agent.db"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_with_headers(url: str, timeout: int = 15) -> str:
    """Executes an HTTP GET request with browser emulation headers."""
    headers = {
        "User-Agent": USER_AGENTS[0],
        "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", errors="replace")


def search_linkedin_jobs(
    keywords: str = "python engineer",
    location: str = "Indonesia",
    start: int = 0,
    limit: int = 10,
    easy_apply_only: bool = True
) -> list:
    """Queries LinkedIn guest search endpoint and returns parsed job summaries with pagination support."""
    encoded_keywords = urllib.parse.quote(keywords)
    encoded_location = urllib.parse.quote(location)
    easy_param = "&f_AL=true" if easy_apply_only else ""

    all_results = []
    seen_ids = set()
    curr_start = start
    # If limit <= 0 ('Semua Lowongan'), allow up to 8 pages (~100-150 jobs)
    max_pages = 8 if limit <= 0 else max(1, (limit + 24) // 25)

    for page_idx in range(max_pages):
        url = (
            f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords={encoded_keywords}&location={encoded_location}{easy_param}&start={curr_start}"
        )
        try:
            content = fetch_with_headers(url)
        except Exception as exc:
            print(f"[LinkedIn Scraper Error] Search request failed at start={curr_start}: {exc}")
            break

        titles = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([\s\S]*?)\s*</h3>', content)
        companies = re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>[\s\S]*?<a[^>]*>\s*([\s\S]*?)\s*</a>', content)
        locations = re.findall(r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>\s*([\s\S]*?)\s*</span>', content)
        links = re.findall(r'<a[^>]*class="[^"]*base-card__full-link[^"]*"[^>]*href="([^"]*)"', content)
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', content)

        if not titles:
            break

        batch_count = 0
        for i in range(len(titles)):
            jid = job_ids[i] if i < len(job_ids) else f"li-{uuid.uuid4().hex[:8]}"
            if jid in seen_ids:
                continue
            seen_ids.add(jid)

            t = html.unescape(titles[i].strip())
            c = html.unescape(companies[i].strip()) if i < len(companies) else "Perusahaan LinkedIn"
            loc = html.unescape(locations[i].strip()) if i < len(locations) else location
            raw_link = links[i] if i < len(links) else ""
            clean_link = raw_link.split("?")[0] if raw_link else f"https://www.linkedin.com/jobs/view/{jid}"

            all_results.append({
                "external_id": jid,
                "title": t,
                "company": c,
                "location": loc,
                "url": clean_link,
            })
            batch_count += 1
            if limit > 0 and len(all_results) >= limit:
                break

        if limit > 0 and len(all_results) >= limit:
            break

        if batch_count == 0:
            break

        curr_start += 25
        time.sleep(0.5)

    if not all_results and easy_apply_only:
        tokens = keywords.strip().split()
        if len(tokens) == 1 and not any(r in keywords.lower() for r in ["developer", "engineer", "programmer", "dev"]):
            fallback_kw = f"{keywords.strip()} Developer"
            return search_linkedin_jobs(
                keywords=fallback_kw,
                location=location,
                start=start,
                limit=limit,
                easy_apply_only=True
            )

    return all_results if limit <= 0 else all_results[:limit]


def fetch_linkedin_job_detail(job_id: str) -> str:
    """Fetches full job posting description text from LinkedIn guest endpoint."""
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        content = fetch_with_headers(url)
        desc_match = re.search(r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>([\s\S]*?)</div>', content)
        if desc_match:
            clean = re.sub(r'<br\s*/?>', '\n', desc_match.group(1))
            clean = re.sub(r'<[^>]+>', ' ', clean)
            clean = html.unescape(clean)
            clean = re.sub(r'[ \t]+', ' ', clean)
            clean = re.sub(r'\n\s*\n+', '\n\n', clean).strip()
            return clean[:3500]
    except Exception as exc:
        print(f"[LinkedIn Scraper Detail Notice] Could not fetch description for {job_id}: {exc}")
    return ""


def scrape_and_ingest_linkedin(keywords: str = "", location: str = "", limit: int = 6, easy_apply_only: bool = True, call_gemini_fn=None) -> dict:
    """Scrapes LinkedIn, deduplicates against database, calculates match scores, and drafts applications for high matches."""
    with get_db() as conn:
        cur = conn.cursor()
        cand = cur.execute("SELECT * FROM candidate_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
        if not cand:
            return {"error": "Tidak ada profil kandidat aktif di sistem."}

        cand_id = cand["id"]
        cand_name = cand["full_name"]
        cand_headline = cand["headline"]

        target_roles = json.loads(cand["target_roles"]) if cand["target_roles"] else ["Python Engineer"]
        preferences = json.loads(cand["preferences"]) if cand["preferences"] else {}
        preferred_modes = [m.lower() for m in preferences.get("work_modes", ["remote"])]

        resume = cur.execute("SELECT * FROM resume_versions WHERE candidate_id = ? AND is_current=1 LIMIT 1", (cand_id,)).fetchone()
        facts = json.loads(resume["structured_facts"]) if resume else {}
        cand_skills = [s.lower() for s in facts.get("skills", ["python", "fastapi", "docker", "sql"])]

    # Default search terms from candidate profile
    search_query = keywords.strip() if keywords else (target_roles[0] if target_roles else "Python Backend Engineer")
    search_loc = location.strip() if location else "Indonesia"

    raw_jobs = search_linkedin_jobs(keywords=search_query, location=search_loc, limit=limit, easy_apply_only=easy_apply_only)
    if not raw_jobs:
        return {
            "success": False,
            "message": f"Tidak ada lowongan ditemukan di LinkedIn untuk kata kunci '{search_query}' di '{search_loc}'.",
            "count": 0,
            "items": []
        }

    ingested_count = 0
    new_jobs = []
    drafts_created = 0

    with get_db() as conn:
        cur = conn.cursor()
        for rj in raw_jobs:
            ext_id = rj["external_id"]
            existing = cur.execute("SELECT id FROM jobs WHERE external_id = ?", (ext_id,)).fetchone()
            if existing:
                continue  # Skip already ingested

            time.sleep(0.4)  # Politeness interval
            description = fetch_linkedin_job_detail(ext_id)
            if not description:
                description = f"Posisi {rj['title']} di {rj['company']}. Lokasi: {rj['location']}."

            job_id = f"job-li-{ext_id}"
            cur.execute("""
                INSERT INTO jobs (id, source, external_id, url, title, company, location, description, status)
                VALUES (?, 'linkedin_guest_api', ?, ?, ?, ?, ?, ?, 'discovered')
            """, (job_id, ext_id, rj["url"], rj["title"], rj["company"], rj["location"], description))

            # Explainable 5-Factor Match Engine
            job_text = f"{rj['title']} {description}".lower()
            matched = [s for s in cand_skills if s in job_text]
            skill_score = min(40, int((len(matched) / max(min(len(cand_skills), 5), 1)) * 40))
            role_score = 20 if any(r.lower() in rj["title"].lower() for r in target_roles) else 5
            loc_text = f"{rj['location']} {description}".lower()
            loc_score = 15 if any(m in loc_text for m in preferred_modes) else 10
            domain_score = 15 if ("senior" in rj["title"].lower() or "ai" in rj["title"].lower() or "engineer" in rj["title"].lower()) else 8
            base_score = 10

            score = min(100, skill_score + role_score + loc_score + domain_score + base_score)
            confidence = "high" if score >= 70 else ("medium" if score >= 50 else "low")

            cur.execute("""
                INSERT OR REPLACE INTO job_matches (id, candidate_id, job_id, score, confidence, evidence, missing_requirements)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                f"jm-{uuid.uuid4().hex[:8]}",
                cand_id,
                job_id,
                score,
                confidence,
                json.dumps([{"skill": s, "source": "resume"} for s in matched]),
                json.dumps([s for s in cand_skills if s not in matched])
            ))

            # Draft application if match score >= 60
            if score >= 60 and call_gemini_fn:
                app_id = f"app-{uuid.uuid4().hex[:8]}"
                gemini_prompt = (
                    f"Kamu adalah AI Career Agent profesional. Tulis draf cover letter Bahasa Indonesia (2-3 paragraf) "
                    f"resmi, elegan, dan siap kirim untuk posisi LinkedIn berikut:\n"
                    f"Posisi: {rj['title']}\n"
                    f"Perusahaan: {rj['company']}\n"
                    f"Deskripsi Lowongan:\n{description[:1200]}\n\n"
                    f"Profil Kandidat:\n"
                    f"Nama: {cand_name}\n"
                    f"Headline: {cand_headline}\n"
                    f"Skill Cocok: {', '.join(matched)}\n"
                    f"Aturan mutlak: Jangan gunakan placeholder ([...]). Jangan mengarang data fiktif. Tanpa emoji."
                )
                ai_letter = call_gemini_fn(gemini_prompt)
                if not ai_letter:
                    ai_letter = (
                        f"Yth. Tim Rekrutmen {rj['company']},\n\n"
                        f"Saya melamar untuk peran {rj['title']}. Dengan keahlian terverifikasi di bidang {', '.join(matched[:3])}, "
                        f"saya siap berkontribusi langsung pada pencapaian tim Anda.\n\n"
                        f"Salam hormat,\n{cand_name}"
                    )

                cur.execute("""
                    INSERT OR REPLACE INTO applications (id, candidate_id, job_id, resume_version_id, status, artifacts, notes)
                    VALUES (?, ?, ?, ?, 'pending_approval', ?, ?)
                """, (
                    app_id,
                    cand_id,
                    job_id,
                    resume["id"] if resume else None,
                    json.dumps({
                        "cover_letter": ai_letter,
                        "matched_skills": matched,
                        "score": score,
                        "model": "gemini-3.5-flash-lite"
                    }),
                    f"Scraped from LinkedIn. Match score: {score}%"
                ))

                cur.execute("""
                    INSERT OR REPLACE INTO approvals (id, application_id, status, requested_artifacts, reviewer)
                    VALUES (?, ?, 'pending', ?, 'Aditya')
                """, (f"appr-{uuid.uuid4().hex[:8]}", app_id, json.dumps({"cover_letter": ai_letter})))
                drafts_created += 1

            ingested_count += 1
            new_jobs.append({
                "id": job_id,
                "title": rj["title"],
                "company": rj["company"],
                "location": rj["location"],
                "score": score,
                "url": rj["url"]
            })

        cur.execute("""
            INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
            VALUES (?, 'scraper', 'linkedin_guest_engine', 'linkedin_scrape_completed', 'jobs', ?, ?)
        """, (
            f"aud-{uuid.uuid4().hex[:8]}",
            cand_id,
            json.dumps({"keywords": search_query, "location": search_loc, "ingested": ingested_count, "drafts": drafts_created})
        ))
        conn.commit()

    return {
        "success": True,
        "keywords": search_query,
        "location": search_loc,
        "ingested_count": ingested_count,
        "drafts_created": drafts_created,
        "jobs": new_jobs,
        "message": f"Berhasil memindai LinkedIn: {ingested_count} lowongan baru ditambahkan ke radar ({drafts_created} draf approval dibuat)."
    }
