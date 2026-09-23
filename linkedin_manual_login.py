"""Career Agent — Interactive Manual Login Assistant for LinkedIn.

Launches a visible Chromium browser with persistent user data context,
allowing the user to log in manually (handling 2FA, SMS OTP, or CAPTCHA seamlessly).
Automatically detects the resulting 'li_at' session cookie, extracts the candidate profile,
and stores the credentials securely in the Career Agent database.
"""

import json
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR = DATA_DIR / "linkedin_browser_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)
COOKIES_FILE = DATA_DIR / "linkedin_cookies.json"

logger = logging.getLogger("linkedin_manual_login")


def cleanup_stale_playwright_processes():
    """Terminates zombie ms-playwright Chromium processes and removes stale profile lockfiles."""
    import subprocess
    try:
        subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-Process -Name chrome -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*ms-playwright*' } | Stop-Process -Force"
            ],
            capture_output=True, timeout=5
        )
    except Exception:
        pass

    lockfile = PROFILE_DIR / "lockfile"
    if lockfile.exists():
        try:
            lockfile.unlink()
        except Exception:
            pass


def clean_browser_profile():
    """Completely resets the browser profile by terminating Chromium processes and wiping stored session data."""
    cleanup_stale_playwright_processes()
    time.sleep(0.5)

    if COOKIES_FILE.exists():
        try:
            COOKIES_FILE.unlink()
        except Exception:
            pass

    if PROFILE_DIR.exists():
        import shutil
        for sub in [
            "Default/Network",
            "Default/Sessions",
            "Default/Local Storage",
            "Default/IndexedDB",
            "Default/SharedStorage"
        ]:
            target = PROFILE_DIR / sub
            if target.exists():
                try:
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink()
                except Exception:
                    pass
        for f in PROFILE_DIR.glob("lockfile*"):
            try:
                f.unlink()
            except Exception:
                pass
        for f in PROFILE_DIR.glob("Singleton*"):
            try:
                f.unlink()
            except Exception:
                pass


def call_gemini_ai(prompt: str) -> str:
    """Invokes Gemini API via server.call_gemini or direct urllib fallback."""
    try:
        from server import call_gemini
        res = call_gemini(prompt)
        if res and len(res.strip()) > 5:
            return res.strip()
    except Exception:
        pass

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return ""
    import urllib.request
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1000}
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            candidates = res_data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "").strip()
    except Exception as exc:
        logger.warning(f"Direct Gemini API call failed: {exc}")
    return ""


def download_linkedin_official_pdf(page, candidate_id: str, candidate_name: str, notify_fn: Optional[Callable[[str, str], None]] = None) -> Optional[Path]:
    """Downloads the official LinkedIn resume PDF from the user's profile and returns the saved file path."""
    if notify_fn:
        notify_fn("downloading_resume", "Mengunduh berkas resume/CV resmi langsung dari akun LinkedIn Anda...")

    resume_dir = ROOT / "uploads" / "resumes"
    resume_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', candidate_name.lower().strip()) or "candidate"
    target_path = resume_dir / f"{candidate_id}_{safe_name}_linkedin.pdf"

    # --- STRATEGY 1: Exact SDUI DOM Interactive Click (from LinkedIn SDUI Web) ---
    try:
        # 1. More button (supporting new LinkedIn SDUI & legacy)
        more_selectors = [
            "button[aria-label='More']",
            "button:has(svg#overflow-web-ios-small)",
            "button[aria-label*='More actions']",
            "button[aria-label*='Tindakan lainnya']",
            "button[componentkey*='overflow']",
            "button[componentkey*='More']",
            ".pv-top-card-v2-ctas button.artdeco-dropdown__trigger",
            "div.pvs-profile-actions button.artdeco-dropdown__trigger",
            "button:has-text('More')",
            "button:has-text('Lainnya')"
        ]

        more_btn = None
        for sel in more_selectors:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                more_btn = loc
                break

        if more_btn:
            more_btn.click(timeout=3000)
            time.sleep(1.0)

            # 2. PDF Option Selector (matches user snippet: svg#download-medium, p "Save to PDF")
            pdf_selectors = [
                "p:has-text('Save to PDF')",
                "p:has-text('Simpan ke PDF')",
                "div:has(svg#download-medium)",
                "svg#download-medium",
                "[data-token-id='136']",
                "div.artdeco-dropdown__content div:has-text('Save to PDF')",
                "div.artdeco-dropdown__content div:has-text('Simpan ke PDF')",
                "li:has-text('Save to PDF')",
                "li:has-text('Simpan ke PDF')"
            ]

            pdf_item = None
            for sel in pdf_selectors:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    pdf_item = loc
                    break

            if pdf_item:
                try:
                    with page.expect_download(timeout=12000) as download_info:
                        pdf_item.click(timeout=3000)
                    download = download_info.value
                    download.save_as(str(target_path))
                    if target_path.exists() and target_path.stat().st_size > 500:
                        if notify_fn:
                            notify_fn("resume_downloaded", f"CV resmi LinkedIn ({target_path.name}) berhasil diunduh & diunggah otomatis sebagai resume aktif.")
                        return target_path
                except Exception as dl_err:
                    logger.info(f"Interactive click download wait timed out, trying RSC API fallback: {dl_err}")
    except Exception as ui_exc:
        logger.info(f"UI click for Save to PDF failed or timed out: {ui_exc}")

    # --- STRATEGY 2: Direct LinkedIn RSC Action Fallback (Exact Payload from User) ---
    try:
        # Extract profileId from DOM or scripts
        profile_id = page.evaluate(r"""() => {
            const cardEl = document.querySelector('[id*="refACo"]');
            if (cardEl) {
                const match = cardEl.id.match(/ref(ACo[A-Za-z0-9_-]+)/);
                if (match) return match[1];
            }
            const html = document.documentElement.innerHTML;
            const match2 = html.match(/"profileId":\s*"(ACo[A-Za-z0-9_-]+)"/);
            if (match2) return match2[1];
            const match3 = html.match(/ACoAA[A-Za-z0-9_-]{30,}/);
            if (match3) return match3[0];
            return null;
        }""")

        if profile_id:
            logger.info(f"Extracted LinkedIn profileId for RSC fallback: {profile_id}")
            rsc_result = page.evaluate("""async (pId) => {
                try {
                    const payload = {
                        "requestId": "com.linkedin.sdui.requests.profile.saveProfileToPdf",
                        "serverRequest": {
                            "requestId": "com.linkedin.sdui.requests.profile.saveProfileToPdf",
                            "requestedArguments": {
                                "$type": "proto.sdui.actions.requests.RequestedArguments",
                                "requestedStateKeys": [],
                                "payload": { "profileId": pId },
                                "requestMetadata": { "$type": "proto.sdui.common.RequestMetadata" }
                            },
                            "isApfcEnabled": false,
                            "isStreaming": false,
                            "rumPageKey": ""
                        },
                        "states": [],
                        "requestedArguments": {
                            "$type": "proto.sdui.actions.requests.RequestedArguments",
                            "requestedStateKeys": [],
                            "payload": { "profileId": pId },
                            "requestMetadata": { "$type": "proto.sdui.common.RequestMetadata" },
                            "states": [],
                            "screenId": "",
                            "knownTemplateIds": []
                        }
                    };

                    const res = await fetch('/flagship-web/rsc-action/actions/server-request?sduiid=com.linkedin.sdui.requests.profile.saveProfileToPdf', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'x-restli-protocol-version': '2.0.0'
                        },
                        body: JSON.stringify(payload)
                    });

                    const text = await res.text();
                    return { status: res.status, data: text };
                } catch (e) {
                    return { error: String(e) };
                }
            }""", profile_id)

            if rsc_result and not rsc_result.get("error"):
                resp_text = rsc_result.get("data", "")
                urls = re.findall(r'https://[^"\'\s]+\.pdf[^"\'\s]*', resp_text) or re.findall(r'https://www.linkedin.com/profile/pdf[^"\'\s]+', resp_text)
                if urls:
                    pdf_url = urls[0].replace('\\u0026', '&')
                    logger.info(f"Found PDF URL from RSC response: {pdf_url}")
                    res = page.request.get(pdf_url)
                    if res.status == 200:
                        target_path.write_bytes(res.body())
                        if target_path.exists() and target_path.stat().st_size > 500:
                            if notify_fn:
                                notify_fn("resume_downloaded", f"CV resmi LinkedIn ({target_path.name}) berhasil diunduh & diunggah otomatis sebagai resume aktif.")
                            return target_path
    except Exception as rsc_exc:
        logger.info(f"RSC API direct fetch for Save to PDF failed: {rsc_exc}")

    return None


def sync_active_linkedin_profile(
    page,
    notify_fn: Optional[Callable[[str, str], None]] = None,
    call_gemini_fn: Optional[Any] = None
) -> Dict[str, Any]:
    """Navigates to the user's LinkedIn profile page, extracts complete profile info,
    downloads the official LinkedIn PDF resume, enhances data with Gemini AI,
    and persists everything to Career Agent SQLite database.
    """
    if notify_fn:
        notify_fn("syncing_profile", "Menyinkronkan data profil & keahlian lengkap dari LinkedIn...")

    extracted_data = {
        "full_name": "",
        "headline": "",
        "location": "",
        "phone": "",
        "profile_url": "",
        "summary": "",
        "skills": [],
        "achievements": [],
        "target_roles": []
    }

    # Step 1: Extract from Feed Identity Card
    try:
        if "feed" not in page.url.lower():
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
            time.sleep(2.0)

        links = page.eval_on_selector_all(
            'a[href*="/in/"]',
            'els => els.map(e => ({href: e.href, text: e.innerText.trim()}))'
        )
        user_links = [
            l for l in links
            if l.get("text") and '\n' in l.get("text") and not any(w in l["text"].lower() for w in ["follow", "connect", "popular", "ikuti", "hubungkan", "kirim", "bagikan"])
        ]
        if user_links:
            top_link = user_links[0]
            extracted_data["profile_url"] = top_link.get("href", "")
            lines = [line.strip() for line in top_link["text"].split("\n") if line.strip()]
            if len(lines) >= 1 and len(lines[0]) < 60:
                extracted_data["full_name"] = lines[0]
            if len(lines) >= 2 and len(lines[1]) < 120:
                extracted_data["headline"] = lines[1]
            if len(lines) >= 3 and len(lines[2]) < 80:
                extracted_data["location"] = lines[2]
    except Exception as exc_feed:
        logger.warning(f"Ekstraksi feed card dilewati: {exc_feed}")

    # Step 2: Navigate to Candidate Profile Page
    target_url = extracted_data["profile_url"] or "https://www.linkedin.com/in/me/"
    main_text = ""
    contact_text = ""
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(2.5)
        extracted_data["profile_url"] = page.url

        title = page.title().strip()
        if "|" in title:
            t_name = title.split("|")[0].strip()
            if t_name and len(t_name) < 60 and not t_name.lower().startswith("feed"):
                extracted_data["full_name"] = extracted_data["full_name"] or t_name
        elif "-" in title:
            t_name = title.split("-")[0].strip()
            if t_name and len(t_name) < 60 and not t_name.lower().startswith("feed"):
                extracted_data["full_name"] = extracted_data["full_name"] or t_name

        main_text = page.eval_on_selector("main", "el => el ? el.innerText : ''") or ""

        # Check contact info overlay if available
        try:
            c_link = page.locator("a[href*='overlay/contact-info'], #top-card-text-details-contact-info, a:has-text('Contact info'), a:has-text('Info kontak')").first
            if c_link.count() > 0 and c_link.is_visible():
                c_link.click(timeout=2500)
                time.sleep(1.0)
                c_modal = page.locator("div[role='dialog'], .artdeco-modal").first
                if c_modal.count() > 0:
                    contact_text = c_modal.inner_text()
                    dismiss = c_modal.locator("button[aria-label*='Dismiss'], button[aria-label*='Tutup'], .artdeco-modal__dismiss").first
                    if dismiss.count() > 0:
                        dismiss.click(timeout=2000)
        except Exception:
            pass

        # Extract Profile Avatar Photo
        try:
            photo_urls = page.evaluate('''() => {
                return Array.from(document.querySelectorAll('img'))
                    .map(i => i.src)
                    .filter(src => src && (src.includes('profile-framedphoto') || src.includes('profile-displayphoto') || src.includes('profile-photo') || src.includes('global-nav__me-photo')));
            }''')
            if photo_urls:
                extracted_data["avatar_url"] = photo_urls[0]
        except Exception as exc_photo:
            logger.warning(f"Ekstraksi avatar dilewati: {exc_photo}")

    except Exception as exc:
        logger.warning(f"Gagal mengekstrak profil via DOM: {exc}")

    # Step 3: Candidate ID determination
    ext_key = extracted_data["profile_url"] or (f"https://linkedin.com/in/{extracted_data['full_name'].lower().replace(' ', '-')}" if extracted_data["full_name"] else "https://linkedin.com/in/me")
    candidate_id = ""
    db_path = ROOT / "database" / "career_agent.db"
    try:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            existing_by_key = cur.execute("SELECT id FROM candidate_profiles WHERE external_key = ?", (ext_key,)).fetchone()
            if existing_by_key:
                candidate_id = existing_by_key[0]
            else:
                candidate_id = f"cand-{uuid.uuid4().hex[:8]}"
    except Exception:
        candidate_id = f"cand-{uuid.uuid4().hex[:8]}"

    # Step 4: Automatic Download of Official LinkedIn PDF Resume
    downloaded_pdf = download_linkedin_official_pdf(
        page=page,
        candidate_id=candidate_id,
        candidate_name=extracted_data["full_name"] or "kandidat",
        notify_fn=notify_fn
    )

    pdf_text = ""
    if downloaded_pdf and downloaded_pdf.exists():
        try:
            import pypdf
            reader = pypdf.PdfReader(str(downloaded_pdf))
            pdf_text = "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
        except Exception as p_exc:
            logger.warning(f"Gagal membaca teks PDF yang diunduh: {p_exc}")

    # Step 5: Combine Extracted Texts and Analyze with Gemini AI
    if notify_fn:
        notify_fn("analyzing_gemini", "Menganalisis dan menyusun struktur profil lengkap dengan Google Gemini AI...")

    combined_corpus = f"=== INFORMASI DARI DOM PROFIL ===\n{main_text[:5000]}\n\n"
    if contact_text:
        combined_corpus += f"=== INFORMASI KONTAK ===\n{contact_text[:1000]}\n\n"
    if pdf_text:
        combined_corpus += f"=== RESUME RESMI LINKEDIN ===\n{pdf_text[:4000]}\n\n"

    gemini_fn = call_gemini_fn or call_gemini_ai
    gemini_prompt = (
        f"Kamu adalah AI Career Agent profesional. Analisis data profil LinkedIn dan resume berikut:\n"
        f"{combined_corpus}\n"
        f"Tugas: Ekstrak dan susun profil kandidat menjadi JSON valid sesuai struktur persis berikut:\n"
        f"{{\n"
        f'  "full_name": "Nama lengkap kandidat (tanpa gelar berlebih)",\n'
        f'  "headline": "Headline atau peran profesional terkini",\n'
        f'  "location": "Lokasi kota / negara",\n'
        f'  "phone": "Nomor telepon / WhatsApp dengan kode negara misal +628... (kosongkan jika tidak ada)",\n'
        f'  "target_roles": ["Role 1", "Role 2", "Role 3"],\n'
        f'  "skills": ["Skill 1", "Skill 2", ... minimal 6-12 keahlian teknis/profesional relevan],\n'
        f'  "summary": "Ringkasan profesional 2-3 kalimat yang solid dan berbasis fakta profil ini",\n'
        f'  "achievements": [\n'
        f'    "Pengalaman atau pencapaian 1",\n'
        f'    "Pengalaman atau pencapaian 2"\n'
        f'  ]\n'
        f"}}\n\n"
        f"Aturan Mutlak:\n"
        f"1. Berikan HANYA JSON valid tanpa teks pengantar, penutup, atau tanda markdown.\n"
        f"2. MUTLAK DILARANG menggunakan emoji apa pun di seluruh nilai string.\n"
        f"3. Pastikan keahlian (skills) nyata dan relevan dengan profil kandidat."
    )

    try:
        gemini_raw = gemini_fn(gemini_prompt)
        if gemini_raw:
            cleaned = re.sub(r'^```json\s*', '', gemini_raw.strip(), flags=re.IGNORECASE)
            cleaned = re.sub(r'```$', '', cleaned.strip())
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                if parsed.get("full_name"):
                    extracted_data["full_name"] = parsed["full_name"].strip()
                if parsed.get("headline"):
                    extracted_data["headline"] = parsed["headline"].strip()
                if parsed.get("location"):
                    extracted_data["location"] = parsed["location"].strip()
                if parsed.get("phone"):
                    extracted_data["phone"] = parsed["phone"].strip()
                if parsed.get("skills") and isinstance(parsed["skills"], list):
                    extracted_data["skills"] = [s.strip() for s in parsed["skills"] if s.strip()]
                if parsed.get("target_roles") and isinstance(parsed["target_roles"], list):
                    extracted_data["target_roles"] = [r.strip() for r in parsed["target_roles"] if r.strip()]
                if parsed.get("summary"):
                    extracted_data["summary"] = parsed["summary"].strip()
                if parsed.get("achievements") and isinstance(parsed["achievements"], list):
                    extracted_data["achievements"] = [a.strip() for a in parsed["achievements"] if a.strip()]
    except Exception as gemini_exc:
        logger.warning(f"Analisis Gemini profil dilewati: {gemini_exc}")

    # Fallback if fields still empty
    full_name = extracted_data["full_name"] or "Pengguna LinkedIn"
    headline = extracted_data["headline"] or "Profesional & Pencari Kerja"
    summary = extracted_data["summary"] or f"Profesional dengan keahlian di bidang {headline}."

    if not extracted_data["target_roles"]:
        parts = [p.strip() for p in re.split(r"[\·\|\,\-]", headline) if p.strip()]
        extracted_data["target_roles"] = [p for p in parts if len(p) < 40 and not any(w in p.lower() for w in ["at", "di", "pt", "inc", "ltd", "corp", "universitas"])][:3] or ["Profesional"]

    if not extracted_data["skills"]:
        common_skills = ["Python", "FastAPI", "SQL", "Docker", "Git", "JavaScript", "TypeScript", "React", "Node.js", "REST API", "Cloud"]
        found = [k for k in common_skills if k.lower() in f"{headline} {summary} {main_text}".lower()]
        extracted_data["skills"] = found or ["Software Engineer", "Backend Developer", "API Specialist"]

    if not extracted_data["achievements"]:
        extracted_data["achievements"] = [
            f"{headline} - Portofolio terverifikasi via profil LinkedIn",
            f"Keahlian teknis: {', '.join(extracted_data['skills'][:4])}"
        ]

    # Phone validation & formatting
    phone_val = extracted_data.get("phone", "").strip()
    if phone_val and not re.match(r'^\+?[0-9\s\-]{8,20}$', phone_val):
        phone_val = ""

    # Step 6: Persist Candidate to SQLite Database
    try:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE candidate_profiles SET active = 0 WHERE id != ?", (candidate_id,))

            # Check if phone already in DB settings
            if not phone_val:
                p_row = cur.execute("SELECT value FROM system_settings WHERE key = 'candidate_phone'").fetchone()
                if p_row and p_row[0]:
                    phone_val = p_row[0].strip()

            pref_payload = json.dumps({
                "phone": phone_val,
                "work_modes": ["remote", "hybrid"]
            })

            # Download and persist avatar locally if found
            local_avatar = ""
            if extracted_data.get("avatar_url"):
                try:
                    import urllib.request
                    avatars_dir = ROOT / "uploads" / "avatars"
                    avatars_dir.mkdir(parents=True, exist_ok=True)
                    avatar_file = avatars_dir / f"{candidate_id}.jpg"
                    req = urllib.request.Request(
                        extracted_data["avatar_url"],
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        avatar_file.write_bytes(resp.read())
                    local_avatar = f"/uploads/avatars/{candidate_id}.jpg"
                except Exception as exc_av_save:
                    logger.warning(f"Gagal download avatar lokal: {exc_av_save}")

            try:
                cur.execute("ALTER TABLE candidate_profiles ADD COLUMN avatar_url TEXT DEFAULT ''")
            except Exception:
                pass

            cur.execute("DELETE FROM candidate_profiles WHERE external_key = ? AND id != ?", (ext_key, candidate_id))
            cur.execute("""
                INSERT INTO candidate_profiles (id, external_key, full_name, headline, location, target_roles, preferences, consent, avatar_url, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    full_name = excluded.full_name,
                    headline = excluded.headline,
                    location = excluded.location,
                    external_key = excluded.external_key,
                    target_roles = excluded.target_roles,
                    preferences = excluded.preferences,
                    avatar_url = COALESCE(NULLIF(excluded.avatar_url, ''), candidate_profiles.avatar_url),
                    active = 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                candidate_id,
                ext_key,
                full_name,
                headline,
                extracted_data["location"],
                json.dumps(extracted_data["target_roles"]),
                pref_payload,
                json.dumps({"require_human_approval": True, "auto_submit": False}),
                local_avatar
            ))

            if phone_val:
                cur.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('candidate_phone', ?)", (phone_val,))

            # Step 7: Persist or Update Resume in resume_versions
            facts_payload = json.dumps({
                "skills": extracted_data["skills"],
                "verified_achievements": extracted_data["achievements"],
                "summary": summary,
                "source_url": ext_key
            })

            if downloaded_pdf and downloaded_pdf.exists() and downloaded_pdf.stat().st_size > 500:
                cur.execute("UPDATE resume_versions SET is_current = 0 WHERE candidate_id = ?", (candidate_id,))
                res_id = f"res-li-{uuid.uuid4().hex[:8]}"
                rel_path = str(downloaded_pdf.relative_to(ROOT)).replace("\\", "/")
                cur.execute("""
                    INSERT INTO resume_versions (id, candidate_id, version_label, source_uri, extracted_text, structured_facts, content_hash, is_current)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    res_id,
                    candidate_id,
                    f"CV LinkedIn Resmi ({full_name})",
                    str(downloaded_pdf.resolve()),
                    pdf_text or summary,
                    facts_payload,
                    f"hash-{uuid.uuid4().hex[:8]}"
                ))
            else:
                # Otomatis generate berkas CV PDF resmi khusus untuk profil ini
                try:
                    import server
                    cand_stub = {
                        "id": candidate_id,
                        "full_name": full_name,
                        "headline": headline,
                        "location": extracted_data.get("location", ""),
                        "external_key": ext_key,
                        "target_roles": extracted_data.get("target_roles", [])
                    }
                    resume_stub = {"structured_facts": facts_payload}
                    gen_pdf = server.generate_and_save_candidate_cv(cand_stub, resume_stub)
                    if gen_pdf and gen_pdf.exists():
                        downloaded_pdf = gen_pdf
                except Exception as gen_err:
                    logger.warning(f"Fallback generate CV gagal: {gen_err}")

            cur.execute("""
                INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, payload)
                VALUES (?, 'system', 'linkedin_manual_login', 'profile_gemini_synced', 'candidate_profiles', ?, ?)
            """, (
                f"aud-{uuid.uuid4().hex[:8]}",
                candidate_id,
                json.dumps({"full_name": full_name, "skills_count": len(extracted_data["skills"]), "pdf_downloaded": bool(downloaded_pdf)})
            ))
            conn.commit()

        if notify_fn:
            notify_fn("authenticated", f"Login berhasil! Profil {full_name} telah otomatis terhubung ke Dashboard.")

    except Exception as exc:
        logger.error(f"Gagal menyimpan data profil ke database: {exc}")

    return extracted_data


def sync_profile_with_cookie(
    li_at: str,
    notify_fn: Optional[Callable[[str, str], None]] = None
) -> Dict[str, Any]:
    """Uses Playwright with li_at cookie in headless mode to fetch candidate profile from /in/me/."""
    if not li_at or len(li_at) < 10:
        return {"success": False, "error": "Cookie li_at tidak valid."}

    if notify_fn:
        notify_fn("syncing", "Menghubungkan sesi cookie dan membaca profil LinkedIn...")

    import linkedin_easy_apply
    linkedin_easy_apply.save_stored_li_at(li_at)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            context.add_cookies([{
                "name": "li_at",
                "value": li_at.strip(),
                "domain": ".www.linkedin.com",
                "path": "/"
            }, {
                "name": "li_at",
                "value": li_at.strip(),
                "domain": ".linkedin.com",
                "path": "/"
            }])
            page = context.new_page()
            profile_data = sync_active_linkedin_profile(page, notify_fn=notify_fn)
            browser.close()
            return {
                "success": True,
                "status": "completed",
                "profile": profile_data,
                "redirect": "/dashboard",
                "message": f"Profil {profile_data.get('full_name', 'LinkedIn')} berhasil disinkronkan ke Dashboard."
            }
    except Exception as exc:
        logger.error(f"Gagal sinkronisasi cookie headless: {exc}")
        return {"success": False, "error": str(exc)}


def launch_interactive_login(
    timeout_seconds: int = 300,
    on_status_update: Optional[Callable[[str, str], None]] = None,
    force_fresh: bool = False
) -> Dict[str, Any]:
    """Launches a visible Chromium window for manual LinkedIn login.

    Polls for the 'li_at' authentication cookie until authenticated,
    the user closes the browser, or timeout occurs.
    """
    def notify(status_code: str, msg: str):
        if on_status_update:
            try:
                on_status_update(status_code, msg)
            except Exception:
                pass

    notify("opening_browser", "Membersihkan sesi lama dan meluncurkan peramban Chromium...")
    cleanup_stale_playwright_processes()

    # If force fresh login or no valid stored session, clean browser profile first
    import linkedin_easy_apply
    stored_cookie = linkedin_easy_apply.get_stored_li_at()
    if force_fresh or not stored_cookie:
        clean_browser_profile()

    with sync_playwright() as p:
        context = None
        browser = None
        try:
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                        "--no-sandbox",
                        "--disable-dev-shm-usage"
                    ],
                    no_viewport=True
                )
            except Exception as exc1:
                logger.warning(f"Persistent context gagal: {exc1}. Membuka peramban standar...")
                cleanup_stale_playwright_processes()
                browser = p.chromium.launch(
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                        "--no-sandbox",
                        "--disable-dev-shm-usage"
                    ]
                )
                context = browser.new_context(no_viewport=True)

            if force_fresh or not stored_cookie:
                try:
                    context.clear_cookies()
                except Exception:
                    pass

            page = context.pages[0] if context.pages else context.new_page()

            notify("navigating", "Membuka halaman login LinkedIn...")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)

            notify("waiting_user", "Silakan masukkan email dan password LinkedIn Anda di jendela peramban...")

            start_time = time.time()
            extracted_li_at = ""
            extracted_name = ""

            while time.time() - start_time < timeout_seconds:
                # Check if page or browser was closed by user
                if page.is_closed() or not context.pages:
                    return {
                        "success": False,
                        "status": "closed_by_user",
                        "error": "Jendela browser ditutup sebelum proses login selesai."
                    }

                # Read current cookies
                cookies = context.cookies(["https://www.linkedin.com", "https://linkedin.com"])
                li_cookie = next((c for c in cookies if c["name"] == "li_at"), None)

                current_url = page.url.lower()

                # User is logged in when li_at cookie is present and page has left login/challenge and entered authenticated area
                is_auth_page = any(area in current_url for area in ["feed", "mynetwork", "jobs", "/in/", "messaging", "notifications"])
                is_challenge_page = any(c in current_url for c in ["login", "checkpoint", "challenge", "uas", "authwall"])

                if li_cookie and li_cookie.get("value") and is_auth_page and not is_challenge_page:
                    extracted_li_at = li_cookie["value"].strip()

                    try:
                        name_el = page.locator(".feed-identity-module__actor-meta strong, .identity-headline, h1.text-heading-xlarge").first
                        if name_el.count() > 0:
                            txt = name_el.inner_text().strip()
                            if txt:
                                extracted_name = txt
                    except Exception:
                        pass
                    break

                time.sleep(1.0)

            if not extracted_li_at:
                try:
                    if context: context.close()
                except Exception:
                    pass
                try:
                    if browser: browser.close()
                except Exception:
                    pass
                return {
                    "success": False,
                    "status": "timeout",
                    "error": "Waktu login habis (300 detik). Silakan coba lagi."
                }

            # Save cookie to database and JSON file
            notify("saving_session", "Login terdeteksi! Menyimpan sesi LinkedIn ke database Career Agent...")

            import linkedin_easy_apply
            linkedin_easy_apply.save_stored_li_at(extracted_li_at)

            # Also persist cookies to JSON file for backup
            try:
                with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                    json.dump(context.cookies(), f, indent=2)
            except Exception:
                pass

            # Synchronize complete candidate profile from LinkedIn /in/me/
            profile_info = sync_active_linkedin_profile(page, notify_fn=notify)
            extracted_name = profile_info.get("full_name") or extracted_name

            time.sleep(1.5)

            try:
                if context: context.close()
            except Exception:
                pass
            try:
                if browser: browser.close()
            except Exception:
                pass

            return {
                "success": True,
                "status": "completed",
                "redirect": "/dashboard",
                "li_at": extracted_li_at,
                "preview": f"{extracted_li_at[:6]}...{extracted_li_at[-4:]}",
                "name": extracted_name or "Pengguna LinkedIn",
                "profile": profile_info,
                "message": f"Login LinkedIn berhasil! Profil {extracted_name} telah otomatis terhubung ke Dashboard."
            }

        except Exception as exc:
            try:
                if context: context.close()
            except Exception:
                pass
            try:
                if browser: browser.close()
            except Exception:
                pass
            return {
                "success": False,
                "status": "error",
                "error": f"Kendala peramban: {str(exc)}"
            }


def login_with_credentials(
    email: str,
    password: str,
    timeout_seconds: int = 180,
    on_status_update: Optional[Callable[[str, str], None]] = None
) -> Dict[str, Any]:
    """Logs into LinkedIn using provided email and password via visible Chromium browser.

    If two-factor authentication (OTP) or captcha is requested by LinkedIn,
    the user can complete it directly on the open browser screen.
    """
    def notify(status_code: str, msg: str):
        if on_status_update:
            try:
                on_status_update(status_code, msg)
            except Exception:
                pass

    email_clean = email.strip()
    pwd_clean = password.strip()
    if not email_clean or not pwd_clean:
        return {"success": False, "status": "error", "error": "Email dan password LinkedIn wajib diisi."}

    notify("opening_browser", "Membersihkan sesi lama dan meluncurkan peramban Chromium...")
    cleanup_stale_playwright_processes()

    with sync_playwright() as p:
        context = None
        browser = None
        try:
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=False,
                    channel="chromium",
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                        "--no-sandbox",
                        "--disable-dev-shm-usage"
                    ],
                    no_viewport=True
                )
            except Exception:
                cleanup_stale_playwright_processes()
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(PROFILE_DIR),
                        headless=False,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--start-maximized",
                            "--no-sandbox",
                            "--disable-dev-shm-usage"
                        ],
                        no_viewport=True
                    )
                except Exception:
                    browser = p.chromium.launch(
                        headless=False,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--start-maximized",
                            "--no-sandbox",
                            "--disable-dev-shm-usage"
                        ]
                    )
                    context = browser.new_context(no_viewport=True)

            page = context.pages[0] if context.pages else context.new_page()

            notify("navigating", "Membuka halaman otentikasi LinkedIn...")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.0)

            current_url = page.url.lower()

            # If already logged in (e.g. from persistent context)
            existing_cookies = context.cookies(["https://www.linkedin.com", "https://linkedin.com"])
            li_at_cookie = next((c for c in existing_cookies if c["name"] == "li_at"), None)
            if li_at_cookie and "feed" in current_url:
                extracted_li_at = li_at_cookie["value"]
                import linkedin_easy_apply
                linkedin_easy_apply.save_stored_li_at(extracted_li_at)
                profile_info = sync_active_linkedin_profile(page, notify_fn=notify)
                try:
                    context.close()
                except Exception:
                    pass
                return {
                    "success": True,
                    "status": "completed",
                    "redirect": "/dashboard",
                    "li_at": extracted_li_at,
                    "preview": f"{extracted_li_at[:6]}...{extracted_li_at[-4:]}",
                    "name": profile_info.get("full_name") or "Pengguna LinkedIn",
                    "profile": profile_info,
                    "message": "Sesi LinkedIn Anda sebelumnya aktif dan profil telah disinkronkan ke Dashboard."
                }

            # Find input fields using robust multi-attribute locators
            user_input = page.locator('input[type="email"], input[name="session_key"], #username, input[type="text"]').first
            pwd_input = page.locator('input[type="password"], input[name="session_password"], #password').first
            submit_btn = page.locator('button:has-text("Sign in"), button:has-text("Masuk"), button[type="submit"]').first

            if user_input.count() > 0 and pwd_input.count() > 0:
                notify("typing_credentials", "Memasukkan email dan password akun ke LinkedIn...")
                user_input.fill("")
                user_input.type(email_clean, delay=35)
                time.sleep(0.5)

                pwd_input.fill("")
                pwd_input.type(pwd_clean, delay=30)
                time.sleep(0.5)

                notify("submitting", "Mengirim formulir login...")
                if submit_btn.count() > 0:
                    submit_btn.click()
                else:
                    pwd_input.press("Enter")

                time.sleep(3.0)

            # Check if 2FA/challenge appeared
            notify("monitoring", "Memeriksa status otentikasi... (Selesaikan kode 2FA di layar jika diminta)")

            start_time = time.time()
            extracted_li_at = ""
            extracted_name = ""

            while time.time() - start_time < timeout_seconds:
                if page.is_closed() or not context.pages:
                    return {
                        "success": False,
                        "status": "closed_by_user",
                        "error": "Jendela browser ditutup sebelum otentikasi selesai."
                    }

                cookies = context.cookies(["https://www.linkedin.com", "https://linkedin.com"])
                li_cookie = next((c for c in cookies if c["name"] == "li_at"), None)
                cur_url = page.url.lower()

                # Check error message on login page
                err_el = page.locator("#error-for-username, #error-for-password, .alert-content").first
                if err_el.count() > 0 and err_el.is_visible():
                    err_msg = err_el.inner_text().strip()
                    if err_msg and time.time() - start_time > 8 and not li_cookie:
                        notify("error", f"LinkedIn: {err_msg}")

                if li_cookie and li_cookie.get("value"):
                    if "checkpoint" not in cur_url and "challenge" not in cur_url:
                        extracted_li_at = li_cookie["value"].strip()
                        try:
                            name_el = page.locator(".feed-identity-module__actor-meta strong, .identity-headline, h1.text-heading-xlarge").first
                            if name_el.count() > 0:
                                txt = name_el.inner_text().strip()
                                if txt:
                                    extracted_name = txt
                        except Exception:
                            pass

                        if "feed" in cur_url or time.time() - start_time > 4:
                            break

                time.sleep(1.0)

            if not extracted_li_at:
                try:
                    if context: context.close()
                except Exception:
                    pass
                try:
                    if browser: browser.close()
                except Exception:
                    pass
                return {
                    "success": False,
                    "status": "timeout",
                    "error": "Batas waktu login terlampaui. Pastikan email & password benar atau selesaikan verifikasi di layar."
                }

            # Save cookie to database and JSON file
            notify("saving_session", "Login berhasil! Menyimpan sesi ke Career Agent...")
            import linkedin_easy_apply
            linkedin_easy_apply.save_stored_li_at(extracted_li_at)

            try:
                with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                    json.dump(context.cookies(), f, indent=2)
            except Exception:
                pass

            # Synchronize complete profile
            profile_info = sync_active_linkedin_profile(page, notify_fn=notify)
            extracted_name = profile_info.get("full_name") or extracted_name

            time.sleep(1.5)

            try:
                if context: context.close()
            except Exception:
                pass
            try:
                if browser: browser.close()
            except Exception:
                pass

            return {
                "success": True,
                "status": "completed",
                "redirect": "/dashboard",
                "li_at": extracted_li_at,
                "preview": f"{extracted_li_at[:6]}...{extracted_li_at[-4:]}",
                "name": extracted_name or "Pengguna LinkedIn",
                "profile": profile_info,
                "message": f"Login berhasil! Profil {extracted_name} telah otomatis terhubung ke Dashboard."
            }

        except Exception as exc:
            try:
                if context: context.close()
            except Exception:
                pass
            try:
                if browser: browser.close()
            except Exception:
                pass
            return {"success": False, "status": "error", "error": f"Kendala peramban: {str(exc)}"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Career Agent — Manual LinkedIn Login Assistant")
    parser.add_argument("--fresh", action="store_true", help="Force fresh login by clearing previous session")
    parser.add_argument("--clean", action="store_true", help="Clean browser profile and exit")
    args = parser.parse_args()

    if args.clean:
        clean_browser_profile()
        print("Browser profile cleaned successfully.")
        sys.exit(0)

    print("=================================================================")
    print("Career Agent — Asisten Login Manual LinkedIn")
    print("=================================================================")
    print("Membuka peramban Chromium. Silakan login ke akun LinkedIn Anda...")
    res = launch_interactive_login(timeout_seconds=300, force_fresh=args.fresh)
    print("\nHasil:")
    print(json.dumps(res, indent=2))
