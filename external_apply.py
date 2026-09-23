"""Career Agent — Universal External ATS Autonomous Application Engine.

Handles automated applications to external job boards and ATS platforms:
- Ashby (jobs.ashbyhq.com)
- Greenhouse (boards.greenhouse.io)
- Lever (jobs.lever.co)
- Workable (apply.workable.com)
- Custom Company Career Portals & External Forms

Inspects dynamic DOM fields, auto-fills identity/contact details, uploads PDF resume,
solves assessment/essay questions using Gemini AI, and executes Dry Run or Live Submit.
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright

logger = logging.getLogger("Career Agent.ExternalApply")
ROOT = Path(__file__).resolve().parent
SCREENSHOT_DIR = ROOT / "uploads" / "applications"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# 1. Ashby ATS Specialized Handler
# ==============================================================================
def parse_ashby_dom(page) -> Dict[str, Any]:
    """Extracts all interactive input elements and contextual questions from an Ashby application page."""
    return page.evaluate("""() => {
        const questions = [];
        document.querySelectorAll('form > div, [class*="application"] [class*="container"], [class*="field"]').forEach(el => {
            const labelEl = el.querySelector('label, [class*="label"], [class*="title"], h3, h4');
            const questionText = labelEl ? labelEl.innerText.trim().split('\\n')[0].trim() : '';
            const inputs = Array.from(el.querySelectorAll('input, textarea, select')).map(inp => {
                let optLabel = inp.closest('label')?.innerText.trim() || inp.parentElement?.innerText.trim() || '';
                optLabel = optLabel.replace(/^[\\r\\n\\s]+|[\\r\\n\\s]+$/g, '').replace(/\\n+/g, ' ');
                return {
                    tag: inp.tagName,
                    type: inp.type || '',
                    id: inp.id || '',
                    name: inp.name || '',
                    value: inp.value || '',
                    required: inp.required || inp.hasAttribute('aria-required') || inp.getAttribute('aria-required') === 'true',
                    placeholder: inp.placeholder || '',
                    optionLabel: optLabel
                };
            });
            if (inputs.length > 0) {
                questions.push({
                    question: questionText,
                    isRequired: el.innerText.includes('*') || inputs.some(i => i.required),
                    inputs: inputs
                });
            }
        });

        const submitBtn = document.querySelector('button[type="submit"], button.ashby-application-form-submit-button');
        return {
            pageTitle: document.title,
            questions: questions,
            hasSubmit: Boolean(submitBtn)
        };
    }""")


def fill_ashby_form(page, candidate_data: Dict[str, Any], resume_path: str, call_gemini_fn=None, dry_run: bool = True) -> Dict[str, Any]:
    """Autofills Ashby application form using candidate data, resume, and Gemini AI."""
    full_name = candidate_data.get("full_name") or candidate_data.get("name", "Pelamar Kerja")
    email = candidate_data.get("email", "pelamar@example.com")
    phone = candidate_data.get("phone", "+6281399887766")
    skills = candidate_data.get("skills", ["Software Engineer", "Backend Developer"])
    summary = candidate_data.get("structured_facts", "") or candidate_data.get("experience_summary", "")

    actions_taken = []

    # Standard Fields
    name_el = page.query_selector("input#_systemfield_name, input[name='_systemfield_name']")
    if name_el:
        name_el.fill(full_name)
        actions_taken.append(f"Filled Name: {full_name}")

    email_el = page.query_selector("input#_systemfield_email, input[name='_systemfield_email']")
    if email_el:
        email_el.fill(email)
        actions_taken.append(f"Filled Email: {email}")

    phone_el = page.query_selector("input[type='tel']")
    if phone_el:
        phone_el.fill(phone)
        actions_taken.append(f"Filled Phone: {phone}")

    resume_input = page.query_selector("input#_systemfield_resume, input[type='file']")
    if resume_input and resume_path and Path(resume_path).exists():
        resume_input.set_input_files(str(Path(resume_path).resolve()))
        actions_taken.append(f"Attached Resume: {Path(resume_path).name}")
        page.wait_for_timeout(2000)

    # Dynamic Questions
    dom_data = parse_ashby_dom(page)
    questions = dom_data.get("questions", [])

    for q in questions:
        q_text = q.get("question", "")
        inputs = q.get("inputs", [])
        if not inputs:
            continue

        q_lower = q_text.lower()
        if any(i.get("id") in ("_systemfield_name", "_systemfield_email", "_systemfield_resume") for i in inputs):
            continue
        if any(i.get("type") == "tel" for i in inputs):
            continue

        radios = [i for i in inputs if i.get("type") == "radio"]
        if radios:
            options = [r.get("optionLabel", "") for r in radios if r.get("optionLabel")]
            chosen_index = 0

            if "gender" in q_lower or "jenis kelamin" in q_lower:
                chosen_index = next((idx for idx, opt in enumerate(options) if "male" in opt.lower() and "female" not in opt.lower()), 0)
            elif "marital" in q_lower or "status" in q_lower:
                chosen_index = next((idx for idx, opt in enumerate(options) if "single" in opt.lower()), 0)
            elif "english" in q_lower:
                chosen_index = next((idx for idx, opt in enumerate(options) if "fluent" in opt.lower() or "native" in opt.lower()), len(radios) - 1)
            elif "role" in q_lower or "looking for" in q_lower:
                chosen_index = next((idx for idx, opt in enumerate(options) if "full-time" in opt.lower()), 0)
            elif "graduate" in q_lower or "university" in q_lower or "degree" in q_lower:
                chosen_index = next((idx for idx, opt in enumerate(options) if "yes" in opt.lower() or "graduated" in opt.lower()), 0)
            elif "difficulties" in q_lower or "approach" in q_lower:
                chosen_index = next((idx for idx, opt in enumerate(options) if "solution" in opt.lower() or "think" in opt.lower()), 0)
            elif "type of job" in q_lower:
                chosen_index = next((idx for idx, opt in enumerate(options) if "secure" in opt.lower() or "growth" in opt.lower()), 0)
            else:
                if call_gemini_fn and options:
                    prompt = (
                        f"Pertanyaan formulir kerja: '{q_text}'\n"
                        f"Pilihan opsi: {options}\n"
                        f"Pilih SATU opsi yang paling profesional dan positif untuk kandidat engineer. "
                        f"Hanya kembalikan indeks opsi berupa angka (0-{len(options)-1})."
                    )
                    ai_reply = call_gemini_fn(prompt).strip()
                    try:
                        parsed_idx = int(re.search(r'\d+', ai_reply).group(0))
                        if 0 <= parsed_idx < len(radios):
                            chosen_index = parsed_idx
                    except Exception:
                        chosen_index = 0

            target_radio_id = radios[chosen_index].get("id")
            if target_radio_id:
                try:
                    page.check(f"input[id='{target_radio_id}']")
                    actions_taken.append(f"Selected radio for '{q_text}': {options[chosen_index] if chosen_index < len(options) else 'option'}")
                except Exception:
                    page.click(f"label[for='{target_radio_id}']")
            continue

        num_inputs = [i for i in inputs if i.get("type") == "number"]
        if num_inputs:
            target_num = num_inputs[0]
            val = "25"
            if "age" in q_lower or "usia" in q_lower or "umur" in q_lower:
                val = "23"
            elif "salary" in q_lower or "gaji" in q_lower or "british" in q_lower or "£" in q_lower:
                val = "1200"
            elif "experience" in q_lower or "years" in q_lower:
                val = "3"
            num_id = target_num.get('id')
            page.fill(f"input[id='{num_id}']", val)
            actions_taken.append(f"Filled number for '{q_text}': {val}")
            continue

        text_inputs = [i for i in inputs if i.get("type") in ("text", "")]
        if text_inputs:
            target_inp = text_inputs[0]
            val = "Indonesian"
            if "nationality" in q_lower or "warga" in q_lower or "country" in q_lower:
                val = "Indonesian"
            elif "linkedin" in q_lower:
                val = candidate_data.get("external_key", "https://www.linkedin.com")
            elif "github" in q_lower or "portfolio" in q_lower:
                val = "https://github.com"
            else:
                if call_gemini_fn:
                    prompt = (
                        f"Berikan jawaban 1-2 kata profesional untuk pertanyaan form kerja: '{q_text}'.\n"
                        f"Kandidat dari Indonesia, bidang Software Engineering."
                    )
                    val = call_gemini_fn(prompt).strip() or "Indonesia"

            inp_id = target_inp.get('id')
            page.fill(f"input[id='{inp_id}']", val)
            actions_taken.append(f"Filled text for '{q_text}': {val}")
            continue

        textareas = [i for i in inputs if i.get("tag") == "TEXTAREA" or i.get("type") == "textarea"]
        if textareas:
            target_ta = textareas[0]
            essay_answer = ""
            if call_gemini_fn:
                prompt = (
                    f"Tulis jawaban esai pelamar yang jujur, tajam, profesional, dan alami dalam Bahasa Inggris "
                    f"untuk pertanyaan wawancara tertulis berikut:\n"
                    f"Pertanyaan: '{q_text}'\n\n"
                    f"Profil Kandidat: {full_name}, Backend/Network Engineer dari Indonesia.\n"
                    f"Keahlian: {', '.join(skills)}.\n"
                    f"Ringkasan: {summary[:300]}.\n\n"
                    f"PENTING: Jangan gunakan klise robotik atau bahasa AI generik (misal 'delve', 'tapestry', 'testament'). "
                    f"Tulis seperti seorang software engineer manusia yang menceritakan pengalaman teknis nyata "
                    f"dalam 2-3 kalimat padat, berbobot, dan membumi. Tanpa emoji."
                )
                essay_answer = call_gemini_fn(prompt).strip()
            if not essay_answer:
                essay_answer = "During my software engineering projects, I optimized data pipelines and automated repetitive server operations using custom Python scripting, improving delivery speed significantly without additional infrastructure costs."

            ta_id = target_ta.get('id')
            page.fill(f"textarea[id='{ta_id}']", essay_answer)
            actions_taken.append(f"Answered essay for '{q_text[:30]}...' ({len(essay_answer)} chars)")
            continue

    page.wait_for_timeout(1000)
    screenshot_name = f"ashby_applied_{int(time.time())}.png"
    screenshot_path = SCREENSHOT_DIR / screenshot_name
    page.screenshot(path=str(screenshot_path), full_page=True)

    submitted = False
    if not dry_run:
        submit_btn = page.query_selector("button.ashby-application-form-submit-button, button[type='submit']")
        if submit_btn:
            submit_btn.click()
            page.wait_for_timeout(4000)
            submitted = True
            actions_taken.append("Clicked 'Submit Application'")

    return {
        "success": True,
        "platform": "Ashby",
        "dry_run": dry_run,
        "submitted": submitted,
        "screenshot_url": f"/uploads/applications/{screenshot_name}",
        "screenshot_path": str(screenshot_path),
        "actions": actions_taken
    }


# ==============================================================================
# 2. Universal Generic External ATS Handler (Greenhouse, Lever, Custom, etc.)
# ==============================================================================
def parse_universal_form_dom(page) -> List[Dict[str, Any]]:
    """Extracts all interactive fields from any generic application form."""
    return page.evaluate("""() => {
        const fields = [];
        const seen = new Set();

        document.querySelectorAll('input, textarea, select').forEach((el, idx) => {
            if (el.type === 'hidden' || el.style.display === 'none' || el.style.visibility === 'hidden') {
                return;
            }

            let label = '';
            // 1. Label for
            if (el.id) {
                const l = document.querySelector(`label[for="${el.id}"]`);
                if (l) label = l.innerText;
            }
            // 2. Parent label
            if (!label) {
                const l = el.closest('label');
                if (l) label = l.innerText;
            }
            // 3. aria-label
            if (!label && el.getAttribute('aria-label')) {
                label = el.getAttribute('aria-label');
            }
            // 4. Preceding / container title
            if (!label) {
                let p = el.parentElement;
                for (let k = 0; k < 3 && p; k++) {
                    const l = p.querySelector('label, [class*="label"], [class*="title"], [class*="heading"]');
                    if (l && l !== el) {
                        label = l.innerText;
                        break;
                    }
                    p = p.parentElement;
                }
            }

            label = (label || '').replace(/\\n+/g, ' ').trim();
            const identifier = el.id || el.name || `field_${idx}`;
            if (seen.has(identifier) && el.type !== 'radio' && el.type !== 'checkbox') {
                return;
            }
            seen.add(identifier);

            let options = [];
            if (el.tagName === 'SELECT') {
                options = Array.from(el.options).map(o => ({ value: o.value, text: o.text.trim() }));
            }

            fields.push({
                index: idx,
                tag: el.tagName,
                type: (el.type || 'text').toLowerCase(),
                id: el.id || '',
                name: el.name || '',
                placeholder: el.placeholder || '',
                required: el.required || el.hasAttribute('aria-required') || el.getAttribute('aria-required') === 'true',
                label: label,
                options: options
            });
        });

        return fields;
    }""")


def fill_universal_form(page, candidate_data: Dict[str, Any], resume_path: str, call_gemini_fn=None, dry_run: bool = True) -> Dict[str, Any]:
    """Universal form filler powered by DOM extraction and Gemini AI."""
    full_name = candidate_data.get("full_name") or candidate_data.get("name", "Pelamar Kerja")
    first_name = full_name.split()[0] if full_name else "Pelamar"
    last_name = " ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else first_name
    email = candidate_data.get("email", "pelamar@example.com")
    phone = candidate_data.get("phone", "+6281399887766")
    skills = candidate_data.get("skills", ["Software Engineer", "Backend Developer"])
    summary = candidate_data.get("structured_facts", "") or candidate_data.get("experience_summary", "")
    headline = candidate_data.get("headline", "Software Engineer")
    linkedin_url = candidate_data.get("external_key", "https://www.linkedin.com")

    actions_taken = []
    fields = parse_universal_form_dom(page)

    # Separate standard identity fields vs questions needing Gemini
    unhandled_fields = []

    for f in fields:
        label_lower = f["label"].lower()
        name_lower = f["name"].lower()
        id_lower = f["id"].lower()
        placeholder_lower = f["placeholder"].lower()
        combined_text = f"{label_lower} {name_lower} {id_lower} {placeholder_lower}"

        tag = f["tag"]
        ftype = f["type"]
        selector = f"input[id='{f['id']}']" if f["id"] else (f"[name='{f['name']}']" if f["name"] else f"{tag.lower()}:nth-of-type({f['index'] + 1})")

        # 1. File Upload (Resume/CV)
        if ftype == "file":
            if resume_path and Path(resume_path).exists():
                try:
                    el = page.query_selector(selector)
                    if el:
                        el.set_input_files(str(Path(resume_path).resolve()))
                        actions_taken.append(f"Attached Resume to: {f['label'] or 'Resume'}")
                        page.wait_for_timeout(1500)
                except Exception as e:
                    logger.warning(f"File upload notice: {e}")
            continue

        # 2. First Name
        if any(k in combined_text for k in ("first name", "firstname", "given name", "nama depan")):
            try:
                page.fill(selector, first_name)
                actions_taken.append(f"Filled First Name: {first_name}")
                continue
            except Exception: pass

        # 3. Last Name
        if any(k in combined_text for k in ("last name", "lastname", "surname", "family name", "nama belakang")):
            try:
                page.fill(selector, last_name)
                actions_taken.append(f"Filled Last Name: {last_name}")
                continue
            except Exception: pass

        # 4. Full Name
        if any(k in combined_text for k in ("full name", "fullname", "your name", "nama lengkap")) or (
            "name" in combined_text and not any(x in combined_text for x in ("company", "school", "first", "last", "file"))
        ):
            try:
                page.fill(selector, full_name)
                actions_taken.append(f"Filled Full Name: {full_name}")
                continue
            except Exception: pass

        # 5. Email
        if ftype == "email" or "email" in combined_text or "e-mail" in combined_text:
            try:
                page.fill(selector, email)
                actions_taken.append(f"Filled Email: {email}")
                continue
            except Exception: pass

        # 6. Phone
        if ftype == "tel" or any(k in combined_text for k in ("phone", "telepon", "mobile", "whatsapp", "contact number")):
            try:
                page.fill(selector, phone)
                actions_taken.append(f"Filled Phone: {phone}")
                continue
            except Exception: pass

        # 7. LinkedIn Profile
        if "linkedin" in combined_text:
            try:
                page.fill(selector, linkedin_url)
                actions_taken.append(f"Filled LinkedIn URL: {linkedin_url}")
                continue
            except Exception: pass

        # 8. GitHub / Portfolio / Website
        if any(k in combined_text for k in ("github", "portfolio", "website", "personal link")):
            try:
                page.fill(selector, "https://github.com")
                actions_taken.append("Filled Portfolio/GitHub URL")
                continue
            except Exception: pass

        # Unhandled field: store for AI solving
        unhandled_fields.append(f)

    # 3. Use Gemini AI to solve custom fields (radios, textareas, numbers, dropdowns)
    if unhandled_fields and call_gemini_fn:
        ai_payload = []
        for uf in unhandled_fields[:15]:  # limit batch to 15 fields
            ai_payload.append({
                "id": uf["id"] or uf["name"],
                "tag": uf["tag"],
                "type": uf["type"],
                "label": uf["label"] or uf["placeholder"],
                "options": uf["options"]
            })

        prompt = (
            f"Kamu adalah AI Autonomous Job Application Filler. Tentukan jawaban terbaik untuk setiap field berikut "
            f"berdasarkan profil pelamar:\n"
            f"Nama: {full_name}\n"
            f"Headline: {headline}\n"
            f"Keahlian: {', '.join(skills)}\n"
            f"Ringkasan Pengalaman: {summary[:300]}\n"
            f"Nomor Telepon: {phone}\n"
            f"Lokasi: Indonesia\n\n"
            f"Daftar Field Formulir:\n{json.dumps(ai_payload, indent=2)}\n\n"
            f"Kembalikan HANYA JSON murni berupa mapping key-value tanpa markdown/backticks:\n"
            f'{{"<field_id>": "<jawaban_teks_atau_angka_atau_opsi>"}}\n'
            f"Untuk esai / textarea, tulis jawaban profesional dalam 2-3 kalimat padat, natural, tanpa klise robotik, tanpa emoji."
        )

        try:
            gemini_res = call_gemini_fn(prompt)
            # clean backticks if any
            clean_json = re.sub(r'^```json\s*|^```\s*|```$', '', gemini_res.strip(), flags=re.MULTILINE).strip()
            answer_map = json.loads(clean_json)

            for uf in unhandled_fields:
                field_key = uf["id"] or uf["name"]
                ans = answer_map.get(field_key)
                if not ans:
                    continue

                selector = f"[id='{uf['id']}']" if uf["id"] else f"[name='{uf['name']}']"

                if uf["tag"] == "SELECT":
                    try:
                        page.select_option(selector, label=str(ans))
                        actions_taken.append(f"Selected '{ans}' for {uf['label']}")
                    except Exception:
                        pass
                elif uf["type"] in ("radio", "checkbox"):
                    try:
                        page.check(selector)
                        actions_taken.append(f"Checked: {uf['label']}")
                    except Exception:
                        pass
                elif uf["tag"] in ("INPUT", "TEXTAREA"):
                    try:
                        page.fill(selector, str(ans))
                        actions_taken.append(f"Filled: {uf['label'][:30]} -> {str(ans)[:30]}...")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Gemini universal fill notice: {e}")

    # 4. Capture Proof Screenshot
    page.wait_for_timeout(1000)
    screenshot_name = f"universal_applied_{int(time.time())}.png"
    screenshot_path = SCREENSHOT_DIR / screenshot_name
    page.screenshot(path=str(screenshot_path), full_page=True)

    # 5. Submit or Dry Run
    submitted = False
    if not dry_run:
        submit_btn = page.query_selector(
            "button[type='submit'], input[type='submit'], button:has-text('Submit'), "
            "button:has-text('Kirim'), button:has-text('Apply')"
        )
        if submit_btn:
            submit_btn.click()
            page.wait_for_timeout(4000)
            submitted = True
            actions_taken.append("Clicked 'Submit Application'")

    return {
        "success": True,
        "platform": "Universal External ATS",
        "dry_run": dry_run,
        "submitted": submitted,
        "screenshot_url": f"/uploads/applications/{screenshot_name}",
        "screenshot_path": str(screenshot_path),
        "actions": actions_taken
    }


# ==============================================================================
# 3. Main Router
# ==============================================================================
def apply_external_job(job_url: str, candidate_data: Dict[str, Any], resume_path: str = "", dry_run: bool = True, call_gemini_fn=None) -> Dict[str, Any]:
    """Orchestrates the entire external job application flow via Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Handle specific routing for Ashby
        target_url = job_url
        if "ashbyhq.com" in job_url and not job_url.endswith("/application"):
            target_url = job_url.rstrip("/") + "/application"

        logger.info(f"Navigating to external ATS: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded", timeout=35000)

        # Look for Apply button if user landed on job description page
        apply_btn = page.query_selector("a:has-text('Apply'), button:has-text('Apply'), [class*='apply']")
        if apply_btn and not any(p in page.url for p in ("/application", "apply")):
            href = apply_btn.get_attribute("href")
            if href:
                if not href.startswith("http"):
                    href = target_url.rstrip("/") + ("/" + href.lstrip("/"))
                page.goto(href, wait_until="domcontentloaded")
            else:
                apply_btn.click()
                page.wait_for_timeout(2500)

        # Wait for form inputs to mount
        try:
            page.wait_for_selector("input, textarea, form", timeout=12000)
            page.wait_for_timeout(1000)
        except Exception:
            pass

        # Router: Ashby specialized or Universal Gemini Engine
        if "ashbyhq.com" in page.url:
            res = fill_ashby_form(page, candidate_data, resume_path, call_gemini_fn=call_gemini_fn, dry_run=dry_run)
        else:
            res = fill_universal_form(page, candidate_data, resume_path, call_gemini_fn=call_gemini_fn, dry_run=dry_run)

        browser.close()
        return res
