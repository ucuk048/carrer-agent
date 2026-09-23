// ==========================================================================
// Career Agent AutoApplier — Pure Client-Side Controller
// Standar: Bersih, intuitif, tanpa embel-embel, mutlak bebas emoji
// ==========================================================================

let allJobs = [];
let applicationsMap = {};
let activeCandidate = null;
let currentFilter = 'all';
let searchQuery = '';
let currentMode = 'dry_run'; // 'dry_run' | 'live'
let isRunning = false;
let stopRequested = false;
let loginPollTimer = null;
let jobKeywordsCatalog = {};
let candidateSkillsList = [];
let selectedJobIds = new Set();
let selectedAppIds = new Set();

// ==========================================================================
// Inisialisasi
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

async function initApp() {
  const searchInput = document.getElementById('input-search-jobs');
  if (searchInput) {
    searchInput.value = '';
    searchQuery = '';
    // Clear delayed browser autofill (e.g. password manager inserting email into search)
    setTimeout(() => {
      if (searchInput && searchInput.value && searchInput.value.includes('@')) {
        searchInput.value = '';
        searchQuery = '';
        if (typeof renderJobsTable === 'function') {
          renderJobsTable();
        }
      }
    }, 300);
  }
  await Promise.all([
    checkLinkedInStatus(),
    loadCandidateProfile(),
    loadJobs(),
    loadKeywordsCatalog()
  ]);
  setupListeners();

  // Handle direct navigation to profile edit after login
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('editProfile') === 'true' || window.location.hash === '#profile') {
    setTimeout(async () => {
      await loadCandidateProfile();
      openProfileModal();
      showToast('Sesi LinkedIn terhubung. Silakan periksa dan sesuaikan data pelamar Anda.');
      window.history.replaceState({}, document.title, window.location.pathname);
    }, 250);
  }
}

function setupListeners() {
  const statusBtn = document.getElementById('btn-linkedin-status');
  if (statusBtn) {
    statusBtn.addEventListener('click', openLinkedInModal);
  }

  const profBtn = document.getElementById('btn-open-profile');
  if (profBtn) {
    profBtn.addEventListener('click', openProfileModal);
  }

  // Clear modal-profile error indications when typing
  document.querySelectorAll('#modal-profile .form-input').forEach(inp => {
    inp.addEventListener('input', () => {
      inp.classList.remove('is-invalid');
      const errEl = document.getElementById('err-' + inp.id);
      if (errEl) errEl.classList.remove('visible');
    });
  });

  // Delegated table actions (immune to quote escaping / inline syntax errors)
  const tbody = document.getElementById('jobs-table-body');
  if (tbody) {
    tbody.addEventListener('click', (e) => {
      const applyBtn = e.target.closest('.btn-apply-single');
      if (applyBtn) {
        const jobId = applyBtn.getAttribute('data-job-id');
        if (jobId) {
          applySingleJob(jobId, applyBtn);
        }
        return;
      }

      const proofBtn = e.target.closest('.btn-view-proof');
      if (proofBtn) {
        const shotUrl = proofBtn.getAttribute('data-screenshot');
        const title = proofBtn.getAttribute('data-title');
        openScreenshotModal(shotUrl, title);
        return;
      }

      const deleteBtn = e.target.closest('.btn-delete-single');
      if (deleteBtn) {
        const jobId = deleteBtn.getAttribute('data-job-id');
        const appId = deleteBtn.getAttribute('data-app-id');
        const title = deleteBtn.getAttribute('data-title') || 'lowongan';
        deleteSingleJob(jobId, appId, title);
        return;
      }
    });
  }
}

// ==========================================================================
// Utilitas UI & Notifikasi
// ==========================================================================
function showToast(message, duration = 3500) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = message;
  toast.style.display = 'flex';
  setTimeout(() => {
    toast.style.display = 'none';
  }, duration);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function getTimeString() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `[${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}]`;
}

function appendTerminalLog(message, type = 'info') {
  const box = document.getElementById('terminal-box');
  if (!box) return;

  const line = document.createElement('div');
  line.className = 'terminal-line';

  const timeSpan = document.createElement('span');
  timeSpan.className = 'terminal-time';
  timeSpan.textContent = getTimeString();

  const textSpan = document.createElement('span');
  textSpan.className = `terminal-text ${type}`;
  textSpan.textContent = message;

  line.appendChild(timeSpan);
  line.appendChild(textSpan);
  box.appendChild(line);

  box.scrollTop = box.scrollHeight;
}

// ==========================================================================
// Mode Selection (Dry Run vs Live Apply)
// ==========================================================================
function selectMode(mode) {
  currentMode = mode;
  const cardDry = document.getElementById('card-mode-dry-run');
  const cardLive = document.getElementById('card-mode-live');

  if (mode === 'dry_run') {
    cardDry?.classList.add('selected');
    cardLive?.classList.remove('selected');
  } else {
    cardLive?.classList.add('selected');
    cardDry?.classList.remove('selected');
  }
}

// ==========================================================================
// LinkedIn Session Management
// ==========================================================================
async function checkLinkedInStatus() {
  const dot = document.getElementById('linkedin-dot');
  const label = document.getElementById('linkedin-account-label');
  const activeCard = document.getElementById('li-active-status-card');
  const activeName = document.getElementById('li-account-name-full');
  const disconnectBtn = document.getElementById('btn-disconnect-li');

  try {
    const res = await fetch('/api/settings/credentials');
    const data = await res.json();

    if (data.linkedin_configured && !window.isSessionExpired) {
      dot?.classList.remove('busy');
      dot?.classList.add('active');
      label.textContent = 'LinkedIn: Terhubung';

      if (activeCard) {
        activeCard.style.display = 'block';
        activeCard.style.borderColor = 'var(--border-subtle)';
        activeCard.style.background = 'var(--bg-surface-secondary)';
      }
      if (activeName) activeName.textContent = `Sesi Cookie Aktif (${data.li_at_preview || 'Tersimpan'})`;
      if (disconnectBtn) disconnectBtn.style.display = 'inline-flex';
      const syncLiModalBtn = document.getElementById('btn-sync-linkedin-modal');
      if (syncLiModalBtn) syncLiModalBtn.style.display = 'inline-flex';
    } else if (window.isSessionExpired) {
      dot?.classList.remove('active');
      dot?.classList.add('busy');
      label.textContent = 'LinkedIn: Sesi Kedaluwarsa';

      if (activeCard) {
        activeCard.style.display = 'block';
        activeCard.style.borderColor = 'var(--warning-border)';
        activeCard.style.background = 'var(--warning-bg)';
      }
      if (activeName) activeName.textContent = 'Sesi Kedaluwarsa (Silakan Login Ulang)';
      if (disconnectBtn) disconnectBtn.style.display = 'inline-flex';
      const syncLiModalBtn = document.getElementById('btn-sync-linkedin-modal');
      if (syncLiModalBtn) syncLiModalBtn.style.display = 'none';
    } else {
      dot?.classList.remove('active', 'busy');
      label.textContent = 'LinkedIn: Belum Terhubung';

      if (activeCard) activeCard.style.display = 'none';
      if (disconnectBtn) disconnectBtn.style.display = 'none';
      const syncLiModalBtn = document.getElementById('btn-sync-linkedin-modal');
      if (syncLiModalBtn) syncLiModalBtn.style.display = 'none';
    }
  } catch (err) {
    if (label) label.textContent = 'LinkedIn: Offline';
  }
}

function openLinkedInModal() {
  document.getElementById('modal-linkedin')?.classList.add('open');
}

function closeLinkedInModal() {
  document.getElementById('modal-linkedin')?.classList.remove('open');
  if (loginPollTimer) {
    clearInterval(loginPollTimer);
    loginPollTimer = null;
  }
}

async function startInteractiveLogin() {
  const indicator = document.getElementById('login-progress-indicator');
  const progressText = document.getElementById('login-progress-text');
  const loginBtn = document.getElementById('btn-browser-login');

  if (indicator) indicator.style.display = 'block';
  if (loginBtn) loginBtn.disabled = true;

  try {
    const res = await fetch('/api/linkedin/manual-login/start', { method: 'POST' });
    const data = await res.json();

    if (progressText) {
      progressText.textContent = data.message || 'Membuka peramban Chromium...';
    }

    // Mulai polling status
    loginPollTimer = setInterval(async () => {
      try {
        const sRes = await fetch('/api/linkedin/manual-login/status');
        const statusData = await sRes.json();

        if (statusData.message && progressText) {
          progressText.textContent = statusData.message;
        }

        if (statusData.status === 'completed') {
          clearInterval(loginPollTimer);
          loginPollTimer = null;
          if (indicator) indicator.style.display = 'none';
          if (loginBtn) loginBtn.disabled = false;

          window.isSessionExpired = false;
          closeLinkedInModal();
          await checkLinkedInStatus();
          await loadCandidateProfile();
          openProfileModal();
          showToast('Login LinkedIn berhasil! Data pelamar otomatis terisi, silakan sesuaikan.');
        } else if (statusData.status === 'timeout' || statusData.status === 'error') {
          clearInterval(loginPollTimer);
          loginPollTimer = null;
          if (indicator) indicator.style.display = 'none';
          if (loginBtn) loginBtn.disabled = false;
          showToast(statusData.message || 'Login peramban dibatalkan atau waktu habis.');
        }
      } catch (e) {
        // Polling error non-blocking
      }
    }, 2000);
  } catch (err) {
    if (indicator) indicator.style.display = 'none';
    if (loginBtn) loginBtn.disabled = false;
    showToast('Gagal memulai peramban login.');
  }
}

async function cancelInteractiveLogin() {
  if (loginPollTimer) {
    clearInterval(loginPollTimer);
    loginPollTimer = null;
  }
  const indicator = document.getElementById('login-progress-indicator');
  const loginBtn = document.getElementById('btn-browser-login');
  if (indicator) indicator.style.display = 'none';
  if (loginBtn) loginBtn.disabled = false;

  try {
    await fetch('/api/linkedin/manual-login/cancel', { method: 'POST' });
  } catch (e) {
    // Non-blocking
  }
  showToast('Proses login peramban dibatalkan.');
}

async function saveManualCookie() {
  const input = document.getElementById('input-li-at');
  const cookieVal = input?.value.trim();
  if (!cookieVal) {
    showToast('Mohon masukkan cookie li_at.');
    return;
  }

  try {
    const res = await fetch('/api/settings/save-credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ li_at: cookieVal })
    });
    const data = await res.json();

    if (res.ok && data.success) {
      window.isSessionExpired = false;
      showToast('Cookie tersimpan. Menyinkronkan profil LinkedIn...');
      try {
        await fetch('/api/profile/sync-linkedin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ li_at: cookieVal })
        });
      } catch (syncErr) {
        console.warn('Sync profile error:', syncErr);
      }
      closeLinkedInModal();
      await checkLinkedInStatus();
      await loadCandidateProfile();
      if (input) input.value = '';
      openProfileModal();
      showToast('Sesi LinkedIn terhubung! Data pelamar otomatis terisi, silakan sesuaikan.');
    } else {
      showToast(data.error || 'Gagal menyimpan cookie.');
    }
  } catch (err) {
    showToast('Kendala jaringan saat menyimpan cookie.');
  }
}

async function disconnectLinkedIn() {
  if (!confirm('Putuskan akun LinkedIn dari sistem Career Agent? Sesi peramban akan dibersihkan agar Anda dapat login dengan akun baru.')) return;
  try {
    const res = await fetch('/api/linkedin/disconnect', { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || 'Akun LinkedIn berhasil diputuskan.');
      await checkLinkedInStatus();
      await loadCandidateProfile();
      closeLinkedInModal();
    }
  } catch (err) {
    showToast('Gagal memutuskan akun.');
  }
}

// ==========================================================================
// Candidate Profile Management
// ==========================================================================
async function loadCandidateProfile() {
  try {
    const res = await fetch('/api/profile');
    const data = await res.json();
    if (res.ok && data.candidate) {
      activeCandidate = data;
      const cand = data.candidate;
      const nameInput = document.getElementById('prof-fullname');
      const locInput = document.getElementById('prof-location');
      const headlineInput = document.getElementById('prof-headline');
      const skillsInput = document.getElementById('prof-skills');
      const expInput = document.getElementById('prof-experience');
      const salInput = document.getElementById('prof-salary');

      if (nameInput) nameInput.value = cand.full_name || '';
      if (locInput) locInput.value = cand.location || '';
      if (headlineInput) headlineInput.value = cand.headline || '';

      // Filter out garbage skills like single character 'a' or empty
      const rawSkills = Array.isArray(data.skills) ? data.skills : [];
      let cleanedSkills = rawSkills.filter(s => s && s.trim().length > 1 && !/^[a-zA-Z]$/.test(s.trim()));
      candidateSkillsList = cleanedSkills;
      if (skillsInput) skillsInput.value = cleanedSkills.join(', ');

      // Resume attachment info
      const resumeBadge = document.getElementById('prof-resume-badge');
      const resumeFileName = document.getElementById('prof-resume-filename');
      if (data.resume && data.resume.filename) {
        if (resumeBadge) {
          resumeBadge.textContent = 'Terlampir';
          resumeBadge.classList.add('attached');
        }
        if (resumeFileName) {
          resumeFileName.textContent = data.resume.filename;
        }
      } else {
        if (resumeBadge) {
          resumeBadge.textContent = 'Belum ada file';
          resumeBadge.classList.remove('attached');
        }
        if (resumeFileName) {
          resumeFileName.textContent = 'Pilih file PDF untuk ekstraksi skill otomatis';
        }
      }

      if (expInput && cand.preferences && cand.preferences.experience_years !== undefined) {
        expInput.value = cand.preferences.experience_years;
      }
      if (salInput && cand.preferences && cand.preferences.expected_salary !== undefined) {
        salInput.value = cand.preferences.expected_salary;
      }

      // Update connected profile banner
      const banner = document.getElementById('banner-connected-profile');
      const bName = document.getElementById('profile-banner-name');
      const bHeadline = document.getElementById('profile-banner-headline');
      const bInitials = document.getElementById('profile-avatar-initials');
      const bSkills = document.getElementById('profile-banner-skills');

      if (banner && cand.full_name) {
        banner.style.display = 'block';
        if (bName) bName.textContent = cand.full_name;
        if (bHeadline) bHeadline.textContent = cand.headline || 'Software Engineer';

        const bAvatarCircle = document.getElementById('profile-avatar-display');
        const parts = cand.full_name.trim().split(' ');
        const inits = parts.length > 1 ? (parts[0][0] + parts[parts.length - 1][0]) : parts[0].slice(0, 2);

        if (bAvatarCircle) {
          if (cand.avatar_url) {
            bAvatarCircle.innerHTML = `
              <img src="${cand.avatar_url}" alt="${escapeHtml(cand.full_name)}" class="profile-avatar-img" onerror="this.remove(); document.getElementById('profile-avatar-initials').style.display='block';">
              <span id="profile-avatar-initials" style="display: none;">${inits.toUpperCase()}</span>
            `;
          } else if (bInitials) {
            bInitials.style.display = 'block';
            bInitials.textContent = inits.toUpperCase();
          }
        }

        const mAvatarCircle = document.getElementById('modal-avatar-display');
        const mAvatarName = document.getElementById('modal-avatar-name');
        if (mAvatarName && cand.full_name) mAvatarName.textContent = cand.full_name;
        if (mAvatarCircle) {
          if (cand.avatar_url) {
            mAvatarCircle.innerHTML = `
              <img src="${cand.avatar_url}" alt="${escapeHtml(cand.full_name)}" class="profile-avatar-img" onerror="this.remove(); document.getElementById('modal-avatar-initials').style.display='block';">
              <span id="modal-avatar-initials" style="display: none;">${inits.toUpperCase()}</span>
            `;
          } else {
            mAvatarCircle.innerHTML = `<span id="modal-avatar-initials">${inits.toUpperCase()}</span>`;
          }
        }

        // Render interactive skill pills in banner
        if (bSkills && cleanedSkills.length > 0) {
          bSkills.innerHTML = cleanedSkills.slice(0, 10).map(s => `
            <span class="skill-pill" onclick="applySkillKeyword('${escapeHtml(s)}')" title="Klik untuk jadikan kata kunci posisi">${escapeHtml(s)}</span>
          `).join('');
        }

        // Smart skill-to-role inference: maps candidate skills to actual job titles
        function inferPositionFromSkills(skills, headline) {
          const skStr = (skills || []).join(' ').toLowerCase();

          if (skStr.includes('penetration testing') || skStr.includes('cybersecurity') || skStr.includes('security')) {
            return 'Cybersecurity';
          }
          if (skStr.includes('network engineering') || skStr.includes('network installation') || skStr.includes('network')) {
            return 'Network Engineer';
          }
          if (skStr.includes('backend') || skStr.includes('python') || skStr.includes('golang') || skStr.includes('api')) {
            return 'Backend Engineer';
          }
          if (skStr.includes('software testing') || skStr.includes('qa')) {
            return 'Software Tester';
          }
          if (skStr.includes('frontend') || skStr.includes('react') || skStr.includes('vue') || skStr.includes('javascript')) {
            return 'Frontend Developer';
          }
          if (skStr.includes('hardware') || skStr.includes('installation') || skStr.includes('support')) {
            return 'IT Support / System Engineer';
          }

          // Check if headline is an actual job role, ignore student/university descriptions
          if (headline && !/(mahasiswa|student|siswa|universitas|university|alumni|institut|school|sekolah|studi)/i.test(headline)) {
            const firstPart = headline.split(/[\|\·\,\-]/)[0].trim();
            if (firstPart && firstPart.length > 3) return firstPart;
          }

          if (skills && skills.length > 0) {
            return skills[0];
          }
          return 'Network Engineer';
        }

        // Auto-fill position search keywords derived directly from skills
        const kwInput = document.getElementById('input-keywords');
        const isDefaultOrStudent = !kwInput?.value.trim() ||
          kwInput.value === 'Backend Engineer' ||
          /(mahasiswa|student|siswa|universitas|university|alumni)/i.test(kwInput.value);

        if (kwInput && isDefaultOrStudent) {
          if (cand.target_roles && cand.target_roles.length > 0 && !/(mahasiswa|student|siswa|universitas)/i.test(cand.target_roles[0])) {
            kwInput.value = cand.target_roles[0];
          } else {
            kwInput.value = inferPositionFromSkills(cleanedSkills, cand.headline);
          }
        }

        // Populate quick-skill-pills below the input field
        const quickContainer = document.getElementById('quick-keywords-container');
        const quickPills = document.getElementById('quick-skill-pills');
        if (quickContainer && quickPills && cleanedSkills.length > 0) {
          quickContainer.style.display = 'flex';
          quickPills.innerHTML = cleanedSkills.slice(0, 6).map(s => `
            <button type="button" class="quick-skill-btn" onclick="applySkillKeyword('${escapeHtml(s)}')" title="Set kata kunci posisi ke: ${escapeHtml(s)}">${escapeHtml(s)}</button>
          `).join('');
        }
      }
    }

    // Load stored phone with valid format check
    const credRes = await fetch('/api/settings/credentials');
    const credData = await credRes.json();
    const phoneInput = document.getElementById('prof-phone');
    let validPhone = credData.phone ? credData.phone.trim() : '';
    if (phoneInput) {
      if (validPhone && validPhone !== '0' && validPhone.length >= 8) {
        phoneInput.value = validPhone;
      } else {
        phoneInput.value = '';
      }
    }
  } catch (err) {
    console.error('Gagal memuat data pelamar:', err);
  }
}

async function uploadCandidateResume(inputEl) {
  const file = inputEl.files && inputEl.files[0];
  if (!file) return;

  if (!file.name.toLowerCase().endsWith('.pdf')) {
    showToast('Harap unggah berkas resume berformat PDF.');
    inputEl.value = '';
    return;
  }

  const reader = new FileReader();
  reader.onload = async () => {
    try {
      showToast('Mengunggah & menganalisis berkas resume...');
      const base64Content = reader.result;
      const res = await fetch('/api/profile/upload-resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: file.name,
          content_base64: base64Content
        })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast(`Resume '${data.filename}' berhasil diunggah!`);
        const resumeBadge = document.getElementById('prof-resume-badge');
        const resumeFileName = document.getElementById('prof-resume-filename');
        if (resumeBadge) {
          resumeBadge.textContent = 'Terlampir';
          resumeBadge.classList.add('attached');
        }
        if (resumeFileName) {
          resumeFileName.textContent = data.filename;
        }

        // Auto-fill skills if extracted
        const skillsInput = document.getElementById('prof-skills');
        if (data.extracted_skills && data.extracted_skills.length > 0) {
          let currentSkills = skillsInput?.value ? skillsInput.value.split(',').map(s => s.trim()).filter(Boolean) : [];
          const combined = Array.from(new Set([...currentSkills, ...data.extracted_skills]));
          if (skillsInput) skillsInput.value = combined.join(', ');
        }

        // Auto-fill phone if extracted and input is currently empty
        const phoneInput = document.getElementById('prof-phone');
        if (data.extracted_phone && phoneInput && (!phoneInput.value || phoneInput.value === '0')) {
          phoneInput.value = data.extracted_phone;
        }
      } else {
        showToast(data.error || 'Gagal mengunggah resume.');
      }
    } catch (err) {
      showToast('Terjadi kesalahan saat mengunggah resume.');
    } finally {
      inputEl.value = '';
    }
  };
  reader.readAsDataURL(file);
}

async function openProfileModal() {
  await loadCandidateProfile();
  document.getElementById('modal-profile')?.classList.add('open');
}

function closeProfileModal() {
  document.getElementById('modal-profile')?.classList.remove('open');
}

async function syncCandidateFromLinkedIn() {
  const btn = document.getElementById('btn-sync-profile');
  const originalText = btn ? btn.innerHTML : 'Tarik Data dari LinkedIn';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-small" style="display: inline-block; width: 14px; height: 14px; border: 2px solid #ccc; border-top-color: var(--primary); border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: middle; margin-right: 6px;"></span>Menyinkronkan...';
  }

  showToast('Memulai sinkronisasi profil & unduh resume resmi dari LinkedIn...');
  try {
    const res = await fetch('/api/profile/sync-linkedin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    const data = await res.json();
    if (data.success) {
      showToast('Profil & resume LinkedIn resmi berhasil disinkronkan!');
      await loadCandidateProfile();
    } else {
      showToast(data.error || 'Gagal menyinkronkan data LinkedIn.');
    }
  } catch (err) {
    showToast('Kendala jaringan saat menyinkronkan data.');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }
}

window.applySkillKeyword = function (skill) {
  const kwInput = document.getElementById('input-keywords');
  if (!kwInput || !skill) return;

  let roleText = skill.trim();
  const sLower = roleText.toLowerCase();

  // Map action skills to standard position keywords
  if (sLower === 'network engineering' || sLower === 'network installation') {
    roleText = 'Network Engineer';
  } else if (sLower === 'penetration testing' || sLower === 'cybersecurity') {
    roleText = 'Cybersecurity';
  } else if (sLower === 'software testing') {
    roleText = 'Software Tester';
  } else if (sLower === 'hardware installation' || sLower === 'software installation') {
    roleText = 'IT Support';
  }

  kwInput.value = roleText;
  kwInput.focus();
  kwInput.classList.add('highlight-pulse');
  setTimeout(() => kwInput.classList.remove('highlight-pulse'), 800);
  showToast(`Kata kunci posisi diubah menjadi: "${roleText}"`);
};

async function loadKeywordsCatalog() {
  try {
    const res = await fetch('/api/jobs/keywords-catalog');
    const data = await res.json();
    if (data.success && data.catalog) {
      jobKeywordsCatalog = data.catalog;
    }
  } catch (err) {
    console.warn('Gagal memuat katalog kata kunci:', err);
  }
}

window.handleCategoryChange = function () {
  const selectEl = document.getElementById('select-category');
  const kwInput = document.getElementById('input-keywords');
  const quickContainer = document.getElementById('quick-keywords-container');
  const quickPills = document.getElementById('quick-skill-pills');
  const quickLabel = document.getElementById('quick-keywords-label');

  if (!selectEl) return;
  const catKey = selectEl.value;

  if (catKey === 'profile_skills') {
    if (quickLabel) quickLabel.textContent = 'Pilihan Cepat Profil:';
    if (candidateSkillsList && candidateSkillsList.length > 0) {
      if (quickContainer) quickContainer.style.display = 'flex';
      if (quickPills) {
        quickPills.innerHTML = candidateSkillsList.slice(0, 8).map(s => `
          <button type="button" class="quick-skill-btn" onclick="applySkillKeyword('${escapeHtml(s)}')" title="Set kata kunci posisi ke: ${escapeHtml(s)}">${escapeHtml(s)}</button>
        `).join('');
      }
    } else {
      if (quickContainer) quickContainer.style.display = 'none';
    }
    showToast('Kategori disetel ke Keahlian Profil Anda');
    return;
  }

  const category = jobKeywordsCatalog[catKey];
  if (category && category.keywords && category.keywords.length > 0) {
    if (kwInput) {
      kwInput.value = category.keywords[0];
      kwInput.classList.add('highlight-pulse');
      setTimeout(() => kwInput.classList.remove('highlight-pulse'), 800);
    }

    if (quickLabel) quickLabel.textContent = `Pilihan Cepat (${category.name}):`;
    if (quickContainer) quickContainer.style.display = 'flex';
    if (quickPills) {
      quickPills.innerHTML = category.keywords.map(kw => `
        <button type="button" class="quick-skill-btn" onclick="applySkillKeyword('${escapeHtml(kw)}')" title="Set kata kunci posisi ke: ${escapeHtml(kw)}">${escapeHtml(kw)}</button>
      `).join('');
    }
    showToast(`Kategori diubah: ${category.name} (${category.keywords.length} kata kunci)`);
  }
};

window.handleApplyCategoryChange = function () {
  const selectEl = document.getElementById('select-apply-category');
  const kwInput = document.getElementById('input-apply-keywords');
  const quickContainer = document.getElementById('apply-quick-keywords-container');
  const quickPills = document.getElementById('apply-quick-skill-pills');
  const quickLabel = document.getElementById('apply-quick-keywords-label');

  if (!selectEl) return;
  const catKey = selectEl.value;

  if (catKey === 'all') {
    if (kwInput) kwInput.value = '';
    if (quickContainer) quickContainer.style.display = 'none';
    showToast('Target Auto Apply: Semua bidang lowongan di radar');
    return;
  }

  if (catKey === 'profile_skills') {
    if (quickLabel) quickLabel.textContent = 'Pilihan Cepat Profil:';
    if (candidateSkillsList && candidateSkillsList.length > 0) {
      if (kwInput) {
        kwInput.value = candidateSkillsList[0];
        kwInput.classList.add('highlight-pulse');
        setTimeout(() => kwInput.classList.remove('highlight-pulse'), 800);
      }
      if (quickContainer) quickContainer.style.display = 'flex';
      if (quickPills) {
        quickPills.innerHTML = candidateSkillsList.slice(0, 8).map(s => `
          <button type="button" class="quick-skill-btn" onclick="applyTargetApplyKeyword('${escapeHtml(s)}')" title="Set kata kunci target ke: ${escapeHtml(s)}">${escapeHtml(s)}</button>
        `).join('');
      }
    } else {
      if (quickContainer) quickContainer.style.display = 'none';
    }
    showToast('Target Auto Apply disetel ke Keahlian Profil Anda');
    return;
  }

  const category = jobKeywordsCatalog[catKey];
  if (category && category.keywords && category.keywords.length > 0) {
    if (kwInput) {
      kwInput.value = category.keywords[0];
      kwInput.classList.add('highlight-pulse');
      setTimeout(() => kwInput.classList.remove('highlight-pulse'), 800);
    }

    if (quickLabel) quickLabel.textContent = `Pilihan Cepat (${category.name}):`;
    if (quickContainer) quickContainer.style.display = 'flex';
    if (quickPills) {
      quickPills.innerHTML = category.keywords.map(kw => `
        <button type="button" class="quick-skill-btn" onclick="applyTargetApplyKeyword('${escapeHtml(kw)}')" title="Set kata kunci target ke: ${escapeHtml(kw)}">${escapeHtml(kw)}</button>
      `).join('');
    }
    showToast(`Target bidang: ${category.name} (${category.keywords.length} kata kunci)`);
  }
};

window.applyTargetApplyKeyword = function (keyword) {
  const kwInput = document.getElementById('input-apply-keywords');
  if (!kwInput || !keyword) return;

  kwInput.value = keyword.trim();
  kwInput.focus();
  kwInput.classList.add('highlight-pulse');
  setTimeout(() => kwInput.classList.remove('highlight-pulse'), 800);
  showToast(`Kata kunci target posisi diubah menjadi: "${keyword.trim()}"`);
};

async function saveProfileData() {
  // Clear any existing error highlights
  document.querySelectorAll('#modal-profile .form-input').forEach(inp => inp.classList.remove('is-invalid'));
  document.querySelectorAll('#modal-profile .field-error-msg').forEach(msg => msg.classList.remove('visible'));

  const nameInput = document.getElementById('prof-fullname');
  const phoneInput = document.getElementById('prof-phone');
  const locInput = document.getElementById('prof-location');
  const headlineInput = document.getElementById('prof-headline');
  const skillsInput = document.getElementById('prof-skills');
  const expInput = document.getElementById('prof-experience');
  const salInput = document.getElementById('prof-salary');

  const name = nameInput?.value.trim() || '';
  const phone = phoneInput?.value.trim() || '';
  const location = locInput?.value.trim() || '';
  const headline = headlineInput?.value.trim() || '';
  const skillsStr = skillsInput?.value.trim() || '';
  const experience = parseInt(expInput?.value || '-1', 10);
  const salary = parseInt(salInput?.value || '0', 10);

  let hasError = false;
  let firstErrorInput = null;

  // 1. Validasi Nama Lengkap
  if (!name || name.length < 3) {
    nameInput?.classList.add('is-invalid');
    document.getElementById('err-prof-fullname')?.classList.add('visible');
    hasError = true;
    if (!firstErrorInput) firstErrorInput = nameInput;
  }

  // 2. Validasi Nomor Telepon (Wajib format nomor seluler Indonesia: 08... atau +628..., 10-14 digit)
  const phoneClean = phone.replace(/[\s\-\(\)]/g, '');
  const phoneRegex = /^(\+62|62|0)8[1-9][0-9]{7,11}$/;
  if (!phoneClean || phoneClean === '0' || !phoneRegex.test(phoneClean)) {
    phoneInput?.classList.add('is-invalid');
    document.getElementById('err-prof-phone')?.classList.add('visible');
    hasError = true;
    if (!firstErrorInput) firstErrorInput = phoneInput;
  }

  // 3. Validasi Lokasi Domisili
  if (!location || location.length < 3) {
    locInput?.classList.add('is-invalid');
    document.getElementById('err-prof-location')?.classList.add('visible');
    hasError = true;
    if (!firstErrorInput) firstErrorInput = locInput;
  }

  // 4. Validasi Headline
  if (!headline || headline.length < 3) {
    headlineInput?.classList.add('is-invalid');
    document.getElementById('err-prof-headline')?.classList.add('visible');
    hasError = true;
    if (!firstErrorInput) firstErrorInput = headlineInput;
  }

  // 5. Validasi Keahlian (Minimal 2 keahlian bermakna, bukan single letter)
  const rawSkills = skillsStr ? skillsStr.split(',').map(s => s.trim()).filter(Boolean) : [];
  const validSkills = rawSkills.filter(s => s.length > 1 && !/^[a-zA-Z]$/.test(s));
  if (validSkills.length < 2) {
    skillsInput?.classList.add('is-invalid');
    document.getElementById('err-prof-skills')?.classList.add('visible');
    hasError = true;
    if (!firstErrorInput) firstErrorInput = skillsInput;
  }

  // 6. Validasi Pengalaman
  if (isNaN(experience) || experience < 0 || experience > 50) {
    expInput?.classList.add('is-invalid');
    document.getElementById('err-prof-experience')?.classList.add('visible');
    hasError = true;
    if (!firstErrorInput) firstErrorInput = expInput;
  }

  // 7. Validasi Ekspektasi Gaji
  if (isNaN(salary) || salary < 1000000) {
    salInput?.classList.add('is-invalid');
    document.getElementById('err-prof-salary')?.classList.add('visible');
    hasError = true;
    if (!firstErrorInput) firstErrorInput = salInput;
  }

  if (hasError) {
    if (firstErrorInput) firstErrorInput.focus();
    showToast('Mohon lengkapi seluruh isian wajib dengan format yang benar.');
    return;
  }

  try {
    // 1. Simpan ke candidate_profiles
    const updateRes = await fetch('/api/profile/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        full_name: name,
        headline: headline,
        location: location,
        skills: validSkills,
        experience_years: experience,
        expected_salary: salary,
        phone: phoneClean
      })
    });
    const updateData = await updateRes.json();

    if (!updateRes.ok) {
      showToast(updateData.error || 'Gagal memperbarui profil.');
      return;
    }

    // 2. Simpan nomor telepon ke settings credentials
    await fetch('/api/settings/save-credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone: phoneClean })
    });

    showToast('Data pelamar berhasil diperbarui & disimpan.');
    closeProfileModal();
    await loadCandidateProfile();
  } catch (err) {
    showToast('Gagal menyimpan data pelamar.');
  }
}

async function syncCandidateFromLinkedIn() {
  const syncBtn = document.getElementById('btn-sync-profile');
  const modalSyncBtn = document.getElementById('btn-sync-linkedin-modal');
  let originalHtml = '';
  if (syncBtn) {
    originalHtml = syncBtn.innerHTML;
    syncBtn.disabled = true;
    syncBtn.innerHTML = '<span class="status-dot busy" style="width:6px;height:6px;margin-right:4px;"></span> Menyinkronkan...';
  }
  if (modalSyncBtn) {
    modalSyncBtn.disabled = true;
  }

  showToast('Menghubungkan ke LinkedIn untuk mengambil profil...');
  try {
    const res = await fetch('/api/profile/sync-linkedin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast('Profil LinkedIn berhasil disinkronkan.');
      await loadCandidateProfile();
    } else {
      showToast(data.error || 'Gagal menyinkronkan profil dari LinkedIn.');
    }
  } catch (err) {
    showToast('Kendala jaringan saat menyinkronkan profil.');
  } finally {
    if (syncBtn) {
      syncBtn.disabled = false;
      syncBtn.innerHTML = originalHtml;
    }
    if (modalSyncBtn) {
      modalSyncBtn.disabled = false;
    }
  }
}

window.syncCandidateFromLinkedIn = syncCandidateFromLinkedIn;
window.openProfileModal = openProfileModal;

function handleScanLimitChange() {
  const sel = document.getElementById('select-scan-limit')?.value;
  const customInp = document.getElementById('input-custom-scan-limit');
  if (customInp) {
    if (sel === 'custom') {
      customInp.style.display = 'block';
      customInp.focus();
    } else {
      customInp.style.display = 'none';
    }
  }
}

function getScanLimit() {
  const sel = document.getElementById('select-scan-limit')?.value || document.getElementById('select-limit')?.value;
  if (sel === 'all' || sel === '0') return 0;
  if (sel === 'custom') {
    const customVal = parseInt(document.getElementById('input-custom-scan-limit')?.value || document.getElementById('input-custom-limit')?.value || '10', 10);
    return isNaN(customVal) || customVal < 1 ? 10 : customVal;
  }
  const parsed = parseInt(sel || '10', 10);
  return isNaN(parsed) ? 10 : parsed;
}

function handleApplyLimitChange() {
  const sel = document.getElementById('select-apply-limit')?.value;
  const customInp = document.getElementById('input-custom-apply-limit');
  if (customInp) {
    if (sel === 'custom') {
      customInp.style.display = 'block';
      customInp.focus();
    } else {
      customInp.style.display = 'none';
    }
  }
}

function getApplyLimit() {
  const sel = document.getElementById('select-apply-limit')?.value;
  if (sel === 'all' || sel === '0') return 0;
  if (sel === 'custom') {
    const customVal = parseInt(document.getElementById('input-custom-apply-limit')?.value || '5', 10);
    return isNaN(customVal) || customVal < 1 ? 5 : customVal;
  }
  const parsed = parseInt(sel || '5', 10);
  return isNaN(parsed) ? 5 : parsed;
}

function handleLimitChange() {
  handleScanLimitChange();
}

function getSelectedLimit() {
  return getScanLimit();
}

window.handleScanLimitChange = handleScanLimitChange;
window.getScanLimit = getScanLimit;
window.handleApplyLimitChange = handleApplyLimitChange;
window.getApplyLimit = getApplyLimit;
window.handleLimitChange = handleLimitChange;
window.getSelectedLimit = getSelectedLimit;

// ==========================================================================
// Job Radar Scanner Engine (Pemindai Lowongan)
// ==========================================================================
async function executeJobScanner() {
  const scanBtn = document.getElementById('btn-scan-jobs');
  const keywords = document.getElementById('input-keywords')?.value.trim() || 'Software Engineer';
  const location = document.getElementById('input-location')?.value.trim() || 'Indonesia';
  const limit = getScanLimit();

  let originalHtml = '';
  if (scanBtn) {
    originalHtml = scanBtn.innerHTML;
    scanBtn.disabled = true;
    scanBtn.innerHTML = '<span class="status-dot busy" style="width:6px;height:6px;margin-right:4px;"></span> Memindai LinkedIn...';
  }

  showToast(`Memindai LinkedIn untuk "${keywords}" (${location})...`);

  try {
    const res = await fetch('/api/jobs/scrape-linkedin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keywords, location, limit, easy_apply_only: true })
    });
    const data = await res.json();

    if (res.ok && data.success) {
      const count = data.ingested_count || 0;
      if (count > 0) {
        showToast(`Pemindaian sukses: ${count} lowongan baru ditambahkan ke radar.`);
      } else {
        showToast(`Daftar diperbarui. Seluruh lowongan terkait sudah ada di radar.`);
      }
    } else {
      showToast(data.message || data.error || 'Kendala saat memindai LinkedIn.');
    }
  } catch (err) {
    showToast('Gagal memindai LinkedIn. Menampilkan data lokal...');
  } finally {
    await loadJobs(true);
    if (scanBtn) {
      scanBtn.disabled = false;
      scanBtn.innerHTML = originalHtml;
    }
  }
}

async function refreshJobList() {
  await executeJobScanner();
}

window.executeJobScanner = executeJobScanner;
window.refreshJobList = refreshJobList;

async function loadJobs(showFeedback = false) {
  try {
    const [jobsRes, appsRes] = await Promise.all([
      fetch('/api/jobs'),
      fetch('/api/applications')
    ]);

    const jobsData = await jobsRes.json();
    const appsData = await appsRes.json();

    allJobs = jobsData.jobs || [];

    // Map applications by job_id
    applicationsMap = {};
    if (appsData.applications) {
      appsData.applications.forEach(app => {
        applicationsMap[app.job_url] = app;
        applicationsMap[app.id] = app;
      });
    }

    updateFilterCounts();
    renderFilteredTable();

    if (showFeedback && !document.getElementById('btn-refresh-jobs')?.disabled) {
      showToast(`Tabel diperbarui: ${allJobs.length} lowongan tersedia.`);
    }
  } catch (err) {
    console.error('Gagal memuat lowongan:', err);
    const tbody = document.getElementById('jobs-table-body');
    if (tbody) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" class="empty-state">
            <p class="empty-state-title">Gagal memuat lowongan</p>
            <p class="empty-state-desc">Pastikan server lokal berjalan di ${window.location.origin}</p>
          </td>
        </tr>
      `;
    }
  }
}

function updateFilterCounts() {
  let pendingCount = 0;
  let appliedCount = 0;
  let externalCount = 0;

  allJobs.forEach(job => {
    const app = getJobApp(job);
    const status = app?.status || job.status;

    if (status === 'applied' || status === 'dry_run_ready' || status === 'ready_for_submit') {
      appliedCount++;
    } else if (status === 'external' || status === 'external_apply_only') {
      externalCount++;
    } else {
      pendingCount++;
    }
  });

  const countAll = document.getElementById('count-all');
  const countPending = document.getElementById('count-pending');
  const countApplied = document.getElementById('count-applied');
  const countExternal = document.getElementById('count-external');

  if (countAll) countAll.textContent = allJobs.length;
  if (countPending) countPending.textContent = pendingCount;
  if (countApplied) countApplied.textContent = appliedCount;
  if (countExternal) countExternal.textContent = externalCount;
}

function getJobApp(job) {
  if (applicationsMap[job.url]) return applicationsMap[job.url];
  if (applicationsMap[job.id]) return applicationsMap[job.id];
  return null;
}

let jobsDataTableInstance = null;

function initOrUpdateDataTable() {
  if (typeof DataTable === 'undefined') return;
  const table = document.getElementById('jobs-data-table');
  if (!table) return;

  if (jobsDataTableInstance) {
    try {
      jobsDataTableInstance.destroy();
    } catch (e) {
      console.warn('DataTable destroy notice:', e);
    }
    jobsDataTableInstance = null;
  }

  // If table has empty-state, do not init
  if (table.querySelector('tbody td.empty-state')) {
    return;
  }

  try {
    jobsDataTableInstance = new DataTable('#jobs-data-table', {
      paging: true,
      pageLength: 10,
      lengthMenu: [
        [10, 25, 50, -1],
        ['10', '25', '50', 'Semua']
      ],
      order: [[4, 'desc']], // Urutkan persentase kecocokan tertinggi (kolom Kesesuaian)
      columnDefs: [
        { targets: 0, orderable: false, searchable: false, width: '36px' },
        { targets: 1, orderable: false, searchable: false, width: '44px' },
        { targets: 6, orderable: false, searchable: false }
      ],
      language: {
        search: "Cari Lowongan:",
        searchPlaceholder: "Ketik kata kunci...",
        lengthMenu: "Tampilkan _MENU_ data",
        info: "Menampilkan _START_ - _END_ dari _TOTAL_ lowongan",
        infoEmpty: "Menampilkan 0 lowongan",
        infoFiltered: "(disaring dari _MAX_ total lowongan)",
        zeroRecords: "Tidak ada lowongan yang cocok",
        paginate: {
          first: "«",
          last: "»",
          next: "›",
          previous: "‹"
        }
      },
      layout: {
        topStart: 'pageLength',
        topEnd: null,
        bottomStart: 'info',
        bottomEnd: 'paging'
      }
    });

    const updateRowNumbers = () => {
      try {
        const info = jobsDataTableInstance.page.info();
        const start = info ? info.start : 0;
        jobsDataTableInstance.rows({ page: 'current' }).nodes().each((row, i) => {
          const numCell = row.querySelector('.col-row-num');
          if (numCell) {
            numCell.textContent = start + i + 1;
          }
        });
      } catch (err) {
        // Fallback jika node belum siap
      }
    };

    jobsDataTableInstance.on('draw', () => {
      updateSelectAllCheckboxState();
      updateRowNumbers();
    });

    // Jalankan sinkronisasi nomor urut baris awal
    updateRowNumbers();
  } catch (err) {
    console.warn('DataTable init notice:', err);
  }
}

function setTableFilter(filter) {
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));

  const activeBtn = document.getElementById(`filter-${filter}`);
  if (activeBtn) activeBtn.classList.add('active');

  if (jobsDataTableInstance) {
    try { jobsDataTableInstance.destroy(); } catch (e) { }
    jobsDataTableInstance = null;
  }

  renderFilteredTable();
}

function handleSearchJobs(val) {
  searchQuery = (val || '').toLowerCase().trim();
  if (jobsDataTableInstance) {
    jobsDataTableInstance.search(searchQuery).draw();
  } else {
    renderFilteredTable();
  }
}

function renderFilteredTable() {
  const tbody = document.getElementById('jobs-table-body');
  if (!tbody) return;

  if (jobsDataTableInstance) {
    try { jobsDataTableInstance.destroy(); } catch (e) { }
    jobsDataTableInstance = null;
  }

  let filtered = allJobs.filter(job => {
    // Search text filter
    if (searchQuery) {
      const text = `${job.title} ${job.company} ${job.location}`.toLowerCase();
      if (!text.includes(searchQuery)) return false;
    }

    // Category filter
    const app = getJobApp(job);
    const status = app?.status || job.status;

    if (currentFilter === 'applied') {
      return status === 'applied' || status === 'dry_run_ready' || status === 'ready_for_submit';
    }
    if (currentFilter === 'external') {
      return status === 'external' || status === 'external_apply_only';
    }
    if (currentFilter === 'pending') {
      return status !== 'applied' && status !== 'dry_run_ready' && status !== 'ready_for_submit' && status !== 'external';
    }
    return true;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="empty-state">
          <p class="empty-state-title">Tidak ada lowongan yang cocok</p>
          <p class="empty-state-desc">Ubah filter atau jalankan pencarian Auto Apply di atas.</p>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map((job, index) => {
    const app = getJobApp(job);
    const status = app?.status || job.status;
    const score = job.score || 75;
    const isChecked = selectedJobIds.has(job.id) ? 'checked' : '';

    // Artifacts & Screenshot
    let screenshotUrl = '';
    if (app && app.artifacts) {
      try {
        const arts = typeof app.artifacts === 'string' ? JSON.parse(app.artifacts) : app.artifacts;
        screenshotUrl = arts?.screenshot || '';
      } catch (e) {
        screenshotUrl = '';
      }
    }

    // Badge Render
    let badgeHtml = '';
    if (status === 'applied') {
      badgeHtml = '<span class="status-badge badge-submitted">Terkirim (Live)</span>';
    } else if (status === 'dry_run_ready' || status === 'ready_for_submit') {
      badgeHtml = '<span class="status-badge badge-simulated">Simulasi Siap</span>';
    } else if (status === 'external' || status === 'external_apply_only') {
      badgeHtml = '<span class="status-badge badge-external">Portal Eksternal</span>';
    } else {
      badgeHtml = '<span class="status-badge badge-pending">Siap Lamar</span>';
    }

    // Actions
    let actionButtons = '';
    if (screenshotUrl) {
      actionButtons += `
        <button class="btn-table btn-view-proof" type="button" data-screenshot="${escapeHtml(screenshotUrl)}" data-title="${escapeHtml(job.title)}">
          Lihat Bukti
        </button>
      `;
    }

    if (status !== 'applied') {
      actionButtons += `
        <button class="btn-table primary btn-apply-single" type="button" data-job-id="${escapeHtml(job.id)}">
          Lamar Ini
        </button>
      `;
    }

    actionButtons += `
      <a class="btn-table" href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer">
        Buka Lowongan
      </a>
    `;

    actionButtons += `
      <button class="btn-table danger btn-delete-single" type="button" data-job-id="${escapeHtml(job.id)}" data-app-id="${escapeHtml(app?.id || '')}" data-title="${escapeHtml(job.title)}" title="Hapus dari daftar">
        Hapus
      </button>
    `;

    return `
      <tr>
        <td style="text-align: center; vertical-align: middle;">
          <input type="checkbox" class="custom-checkbox job-checkbox" data-job-id="${escapeHtml(job.id)}" data-app-id="${escapeHtml(app?.id || '')}" ${isChecked} onchange="handleJobCheckboxChange(this)" />
        </td>
        <td class="col-row-num" style="text-align: center; vertical-align: middle; color: var(--text-tertiary); font-size: 12px; font-weight: 500;">
          ${index + 1}
        </td>
        <td>
          <span class="job-title-cell">${escapeHtml(job.title)}</span>
          <span class="job-company-cell">${escapeHtml(job.company)}</span>
        </td>
        <td>${escapeHtml(job.location || 'Indonesia')}</td>
        <td>
          <strong style="color: ${score >= 75 ? 'var(--success)' : 'var(--text-primary)'}; font-weight: 600;">
            ${score}%
          </strong>
        </td>
        <td>${badgeHtml}</td>
        <td style="text-align: right;">
          <div class="action-btn-group" style="justify-content: flex-end;">
            ${actionButtons}
          </div>
        </td>
      </tr>
    `;
  }).join('');

  initOrUpdateDataTable();
  updateSelectAllCheckboxState();
}

// ==========================================================================
// Seleksi Massal & Penghapusan Lowongan
// ==========================================================================
function handleJobCheckboxChange(cb) {
  const jobId = cb.getAttribute('data-job-id');
  const appId = cb.getAttribute('data-app-id');
  if (cb.checked) {
    if (jobId) selectedJobIds.add(jobId);
    if (appId) selectedAppIds.add(appId);
  } else {
    if (jobId) selectedJobIds.delete(jobId);
    if (appId) selectedAppIds.delete(appId);
  }
  updateBatchActionsBar();
  updateSelectAllCheckboxState();
}

function toggleSelectAllJobs(checked) {
  const checkboxes = document.querySelectorAll('#jobs-table-body .job-checkbox');
  checkboxes.forEach(cb => {
    cb.checked = checked;
    const jobId = cb.getAttribute('data-job-id');
    const appId = cb.getAttribute('data-app-id');
    if (checked) {
      if (jobId) selectedJobIds.add(jobId);
      if (appId) selectedAppIds.add(appId);
    } else {
      if (jobId) selectedJobIds.delete(jobId);
      if (appId) selectedAppIds.delete(appId);
    }
  });
  updateBatchActionsBar();
}

function updateSelectAllCheckboxState() {
  const selectAll = document.getElementById('checkbox-select-all');
  if (!selectAll) return;
  const checkboxes = document.querySelectorAll('#jobs-table-body .job-checkbox');
  if (checkboxes.length === 0) {
    selectAll.checked = false;
    selectAll.indeterminate = false;
    return;
  }
  const checkedCount = Array.from(checkboxes).filter(cb => cb.checked).length;
  selectAll.checked = checkedCount === checkboxes.length;
  selectAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
}

function updateBatchActionsBar() {
  const bar = document.getElementById('batch-actions-bar');
  const countBadge = document.getElementById('batch-selected-count');
  const applyCount = document.getElementById('batch-apply-count');
  const deleteCount = document.getElementById('batch-delete-count');
  const count = selectedJobIds.size;

  if (count > 0) {
    if (bar) bar.style.display = 'flex';
    if (countBadge) countBadge.textContent = `${count} Terpilih`;
    if (applyCount) applyCount.textContent = count;
    if (deleteCount) deleteCount.textContent = count;
  } else {
    if (bar) bar.style.display = 'none';
  }
}

function clearJobSelection() {
  selectedJobIds.clear();
  selectedAppIds.clear();
  document.querySelectorAll('#jobs-table-body .job-checkbox').forEach(cb => cb.checked = false);
  const selectAll = document.getElementById('checkbox-select-all');
  if (selectAll) {
    selectAll.checked = false;
    selectAll.indeterminate = false;
  }
  updateBatchActionsBar();
}

async function deleteSingleJob(jobId, appId, title) {
  if (!jobId && !appId) return;
  const confirmMsg = `Hapus "${title}" dari daftar lowongan dan riwayat lamaran? Tindakan ini tidak dapat dibatalkan.`;
  if (!confirm(confirmMsg)) return;

  try {
    showToast(`Menghapus "${title}"...`);
    const res = await fetch('/api/applications/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_ids: jobId ? [jobId] : [],
        application_ids: appId ? [appId] : []
      })
    });
    const data = await res.json();
    if (data.success) {
      if (jobId) selectedJobIds.delete(jobId);
      if (appId) selectedAppIds.delete(appId);
      updateBatchActionsBar();
      showToast(`Lowongan "${title}" berhasil dihapus.`);
      await loadJobs(true);
    } else {
      showToast(data.error || 'Gagal menghapus lowongan.');
    }
  } catch (err) {
    showToast('Kendala koneksi saat menghapus lowongan.');
  }
}

async function handleBatchDeleteSelected() {
  const count = selectedJobIds.size;
  if (count === 0) return;

  const confirmMsg = `Apakah Anda yakin ingin menghapus ${count} lowongan/lamaran terpilih secara permanen? Tindakan ini tidak dapat dibatalkan.`;
  if (!confirm(confirmMsg)) return;

  const btn = document.getElementById('btn-batch-delete');
  const originalText = btn ? btn.innerHTML : 'Hapus Terpilih';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = 'Menghapus...';
  }

  showToast(`Menghapus ${count} data lowongan terpilih...`);
  try {
    const res = await fetch('/api/applications/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_ids: Array.from(selectedJobIds),
        application_ids: Array.from(selectedAppIds)
      })
    });
    const data = await res.json();
    if (data.success) {
      clearJobSelection();
      showToast(`Berhasil menghapus ${count} lowongan dari database.`);
      await loadJobs(true);
    } else {
      showToast(data.error || 'Gagal menghapus data terpilih.');
    }
  } catch (err) {
    showToast('Kendala jaringan saat menghapus data terpilih.');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }
}

async function handleBatchApplySelected() {
  const targetIds = Array.from(selectedJobIds);
  if (targetIds.length === 0) return;

  const targetJobs = allJobs.filter(j => targetIds.includes(j.id));
  const count = targetJobs.length;

  const modeName = currentMode === 'live' ? 'Kirim Langsung' : 'Simulasi (Dry Run)';
  const confirmMsg = `Lamar ${count} lowongan terpilih dalam mode [${modeName}]?`;
  if (!confirm(confirmMsg)) return;

  if (isRunning) {
    showToast('Proses pengajuan lain sedang berjalan.');
    return;
  }

  const monitorCard = document.getElementById('monitor-card');
  if (monitorCard) {
    monitorCard.style.display = 'block';
    monitorCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  isRunning = true;
  stopRequested = false;
  appendTerminalLog(`Memulai pengajuan massal ${count} lowongan terpilih [Mode: ${modeName}]`, 'info');

  const progressBar = document.getElementById('progress-bar');
  const counterEl = document.getElementById('monitor-counter');
  const statusBadge = document.getElementById('monitor-status-badge');
  if (statusBadge) statusBadge.textContent = 'Sedang Berjalan...';

  let successCount = 0;
  let failCount = 0;

  for (let i = 0; i < targetJobs.length; i++) {
    if (stopRequested) {
      appendTerminalLog('Pengajuan massal dihentikan oleh pengguna.', 'warn');
      break;
    }

    const job = targetJobs[i];
    const pct = Math.round(((i + 1) / count) * 100);
    if (progressBar) progressBar.style.width = `${pct}%`;
    if (counterEl) counterEl.textContent = `${i + 1} / ${count}`;

    appendTerminalLog(`[${i + 1}/${count}] Memproses: ${job.title} - ${job.company}...`, 'info');

    try {
      const res = await fetch('/api/jobs/easy-apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: job.id,
          job_url: job.url,
          dry_run: currentMode === 'dry_run'
        })
      });
      const data = await res.json();
      if (data.success) {
        successCount++;
        appendTerminalLog(`Sukses: ${job.title} terproses (${data.status}).`, 'success');
      } else {
        failCount++;
        appendTerminalLog(`Pemberitahuan (${job.title}): ${data.message || data.error || 'Dilewati'}`, 'warn');
      }
    } catch (err) {
      failCount++;
      appendTerminalLog(`Gagal (${job.title}): ${err.message}`, 'error');
    }

    if (i < targetJobs.length - 1 && !stopRequested) {
      await new Promise(r => setTimeout(r, 2000));
    }
  }

  isRunning = false;
  if (statusBadge) statusBadge.textContent = 'Selesai';
  appendTerminalLog(`Selesai: ${successCount} berhasil, ${failCount} dilewati/gagal dari ${count} lowongan terpilih.`, 'success');
  showToast(`Selesai: ${successCount} lowongan terpilih berhasil diproses.`);
  clearJobSelection();
  await loadJobs(true);
}

// Window global exports
window.handleJobCheckboxChange = handleJobCheckboxChange;
window.toggleSelectAllJobs = toggleSelectAllJobs;
window.updateSelectAllCheckboxState = updateSelectAllCheckboxState;
window.clearJobSelection = clearJobSelection;
window.deleteSingleJob = deleteSingleJob;
window.handleBatchDeleteSelected = handleBatchDeleteSelected;
window.handleBatchApplySelected = handleBatchApplySelected;

// ==========================================================================
// Auto Apply Main Execution Engine
// ==========================================================================
async function startAutoApply() {
  if (isRunning) return;

  // Periksa koneksi LinkedIn terlebih dahulu
  const credRes = await fetch('/api/settings/credentials');
  const credData = await credRes.json();
  if (!credData.linkedin_configured) {
    showToast('Akun LinkedIn belum terhubung. Silakan login terlebih dahulu.');
    openLinkedInModal();
    return;
  }

  const targetCategory = document.getElementById('select-apply-category')?.value || 'all';
  const targetKeywords = document.getElementById('input-apply-keywords')?.value.trim() || '';
  const targetLocation = document.getElementById('input-apply-location')?.value.trim() || '';
  const minScore = parseInt(document.getElementById('select-min-score')?.value || '0', 10);
  const limit = getApplyLimit();

  // Helper: Validasi kecocokan lowongan dengan kata kunci posisi
  function jobMatchesKeyword(job, kw) {
    if (!kw) return true;
    const cleanKw = kw.toLowerCase().trim();
    if (!cleanKw) return true;

    const title = (job.title || '').toLowerCase();
    const desc = (job.description || '').toLowerCase();
    const comp = (job.company || '').toLowerCase();
    const loc = (job.location || '').toLowerCase();
    const fullText = `${title} ${desc} ${comp} ${loc}`;

    // 1. Pencocokan langsung frase
    if (fullText.includes(cleanKw)) return true;

    // 2. Pencocokan tanpa spasi/tanda hubung (misal "cybersecurity" cocok dengan "cyber security")
    const noSpaceKw = cleanKw.replace(/[\s\-_]+/g, '');
    const noSpaceText = fullText.replace(/[\s\-_]+/g, '');
    if (noSpaceText.includes(noSpaceKw)) return true;

    // 3. Pencocokan kata kunci jamak
    const words = cleanKw.split(/[\s\-_]+/).filter(w => w.length >= 3);
    if (words.length > 1) {
      if (words.every(w => fullText.includes(w))) return true;
      if (words.some(w => title.includes(w) && w.length >= 4)) return true;
    }
    return false;
  }

  // Helper: Validasi kecocokan lowongan dengan lokasi target
  function jobMatchesLocation(job, loc) {
    if (!loc) return true;
    const cleanLoc = loc.toLowerCase().trim();
    if (!cleanLoc) return true;

    const jobLoc = (job.location || '').toLowerCase();
    const title = (job.title || '').toLowerCase();
    const desc = (job.description || '').toLowerCase();
    const fullLocText = `${jobLoc} ${title} ${desc}`;

    if (fullLocText.includes(cleanLoc)) return true;
    const noSpaceLoc = cleanLoc.replace(/[\s\-_]+/g, '');
    const noSpaceText = fullLocText.replace(/[\s\-_]+/g, '');
    if (noSpaceText.includes(noSpaceLoc)) return true;

    const words = cleanLoc.split(/[\s\-_]+/).filter(w => w.length >= 3);
    if (words.length > 0 && words.every(w => fullLocText.includes(w))) return true;
    return false;
  }

  // Saring lowongan siap lamar dari radar lokal
  let jobsToProcess = allJobs.filter(j => {
    const app = getJobApp(j);
    const status = app?.status || j.status;
    const isAvailable = (status !== 'applied' && status !== 'external');
    if (!isAvailable) return false;

    // Filter skor minimal
    const score = j.score || 75;
    if (minScore > 0 && score < minScore) return false;

    // Filter lokasi target bila diisi
    if (targetLocation && !jobMatchesLocation(j, targetLocation)) return false;

    // Filter posisi / kata kunci target bila diisi
    if (targetKeywords) {
      if (!jobMatchesKeyword(j, targetKeywords)) return false;
    } else if (targetCategory !== 'all') {
      // Jika input teks kosong namun kategori tertentu dipilih
      if (targetCategory === 'profile_skills') {
        if (candidateSkillsList && candidateSkillsList.length > 0) {
          const matchSkill = candidateSkillsList.some(s => jobMatchesKeyword(j, s));
          if (!matchSkill) return false;
        }
      } else {
        const cat = jobKeywordsCatalog[targetCategory];
        if (cat && cat.keywords && cat.keywords.length > 0) {
          const matchCat = cat.keywords.some(kw => jobMatchesKeyword(j, kw));
          if (!matchCat) return false;
        }
      }
    }

    return true;
  });

  // Terapkan kuota batas kirim jika bukan "Semua"
  if (limit > 0 && jobsToProcess.length > limit) {
    jobsToProcess = jobsToProcess.slice(0, limit);
  }

  // Format label filter untuk log
  const filterParts = [];
  if (targetKeywords) {
    filterParts.push(`Posisi: "${targetKeywords}"`);
  } else if (targetCategory !== 'all') {
    filterParts.push(`Bidang: ${jobKeywordsCatalog[targetCategory]?.name || targetCategory}`);
  }
  if (targetLocation) {
    filterParts.push(`Lokasi: "${targetLocation}"`);
  }
  if (minScore > 0) {
    filterParts.push(`Skor≥${minScore}%`);
  }
  const filterDesc = filterParts.length > 0 ? filterParts.join(' | ') : 'Semua Lowongan di Radar';

  if (jobsToProcess.length === 0) {
    showToast('Tidak ada lowongan siap kirim yang cocok dengan kriteria filter.');
    appendTerminalLog(`Tidak ditemukan lowongan siap kirim di radar dengan kriteria: Target=${filterDesc}, Skor≥${minScore}%.`, 'warn');
    appendTerminalLog('Gunakan Panel 1 (Pemindai Lowongan) di atas untuk memindai lowongan LinkedIn baru ke radar.', 'info');
    return;
  }

  // Set running state
  isRunning = true;
  stopRequested = false;

  const btnStart = document.getElementById('btn-start-apply');
  const btnStop = document.getElementById('btn-stop-apply');
  const monitorCard = document.getElementById('monitor-card');
  const statusBadge = document.getElementById('monitor-status-badge');
  const stepDesc = document.getElementById('monitor-step-desc');
  const counterEl = document.getElementById('monitor-counter');
  const progressBar = document.getElementById('progress-bar');
  const terminalBox = document.getElementById('terminal-box');

  if (btnStart) btnStart.disabled = true;
  if (btnStop) btnStop.style.display = 'inline-flex';
  if (monitorCard) monitorCard.classList.add('active');
  if (terminalBox) terminalBox.innerHTML = '';

  const modeLabel = currentMode === 'dry_run' ? 'Simulasi (Dry Run)' : 'Kirim Langsung (Live Apply)';
  const limitLabel = limit === 0 ? 'Semua Lowongan Siap Lamar' : `${limit} lowongan`;
  appendTerminalLog(`Memulai sesi Pengiriman Otomatis [Mode: ${modeLabel}]...`, 'info');
  appendTerminalLog(`Target: ${limitLabel} | Filter: ${filterDesc} | Skor minimal: ${minScore > 0 ? minScore + '%' : 'Semua'}.`, 'info');
  appendTerminalLog(`Ditemukan ${jobsToProcess.length} lowongan siap diproses pada radar.`, 'info');

  if (statusBadge) statusBadge.textContent = 'Mempersiapkan Form...';
  if (stepDesc) stepDesc.textContent = `Menyiapkan ${jobsToProcess.length} pengajuan lowongan...`;

  try {
    // Step 3: Loop dan proses pengisian tiap lowongan
    let processed = 0;
    const isDryRun = (currentMode === 'dry_run');

    for (let i = 0; i < jobsToProcess.length; i++) {
      if (stopRequested) {
        appendTerminalLog('Proses pengisian dihentikan oleh pengguna.', 'warn');
        break;
      }

      const job = jobsToProcess[i];
      processed++;

      // Update UI Progress
      const pct = Math.round((processed / jobsToProcess.length) * 100);
      if (progressBar) progressBar.style.width = `${pct}%`;
      if (counterEl) counterEl.textContent = `${processed} / ${jobsToProcess.length}`;
      if (statusBadge) statusBadge.textContent = `Memproses #${processed}`;
      if (stepDesc) stepDesc.textContent = `Mengisi: ${job.title} (${job.company})...`;

      appendTerminalLog(`[${processed}/${jobsToProcess.length}] Membuka lowongan: ${job.title} di ${job.company}...`, 'info');

      try {
        const applyRes = await fetch('/api/jobs/easy-apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            job_id: job.id,
            dry_run: isDryRun
          })
        });
        const applyData = await applyRes.json();

        if (applyData.success) {
          const platformName = applyData.platform || 'LinkedIn';
          if (applyData.status === 'submitted') {
            appendTerminalLog(`Sukses: Lamaran ke ${job.company} terkirim langsung (${platformName})!`, 'success');
          } else {
            appendTerminalLog(`Simulasi Siap: Formulir ${platformName} terisi lengkap via Gemini AI. Screenshot disimpan.`, 'success');
          }
        } else if (applyData.status === 'external_apply_only') {
          appendTerminalLog(`Info: Lowongan ${job.company} mengarah ke portal eksternal yang belum terpetakan.`, 'warn');
        } else {
          appendTerminalLog(`Dilewati: ${applyData.message || applyData.error || 'Formulir memerlukan input spesifik'}`, 'warn');
        }
      } catch (applyErr) {
        appendTerminalLog(`Kendala koneksi pada lowongan ${job.title}: ${applyErr.message}`, 'error');
      }

      // Perbarui tabel setiap selesai 1 item
      await loadJobs();

      // Jeda manusiawi antar lowongan jika bukan item terakhir
      if (i < jobsToProcess.length - 1 && !stopRequested) {
        appendTerminalLog('Jeda anti-deteksi bot (2 detik)...', 'info');
        await new Promise(r => setTimeout(r, 2000));
      }
    }

    finishAutoApply(true);
  } catch (err) {
    appendTerminalLog(`Kendala fatal eksekusi: ${err.message}`, 'error');
    finishAutoApply(false);
  }
}

function stopAutoApply() {
  stopRequested = true;
  appendTerminalLog('Permintaan penghentian diterima. Menunggu proses aktif selesai...', 'warn');
}

function finishAutoApply(isSuccess) {
  isRunning = false;
  stopRequested = false;

  const btnStart = document.getElementById('btn-start-apply');
  const btnStop = document.getElementById('btn-stop-apply');
  const statusBadge = document.getElementById('monitor-status-badge');
  const stepDesc = document.getElementById('monitor-step-desc');

  if (btnStart) btnStart.disabled = false;
  if (btnStop) btnStop.style.display = 'none';

  if (statusBadge) {
    statusBadge.textContent = isSuccess ? 'Selesai' : 'Berhenti';
    statusBadge.style.color = isSuccess ? 'var(--success)' : 'var(--danger)';
  }
  if (stepDesc) {
    stepDesc.textContent = isSuccess ? 'Semua lowongan selesai diproses.' : 'Eksekusi selesai dengan catatan.';
  }

  appendTerminalLog('Sesi Auto Apply selesai.', 'info');
  showToast(isSuccess ? 'Siklus Auto Apply selesai dijalankan.' : 'Proses bot telah berakhir.');
}

// ==========================================================================
// Single Job Application Trigger
// ==========================================================================
async function applySingleJob(jobId, buttonEl) {
  const job = allJobs.find(j => j.id === jobId);
  const jobTitle = job ? job.title : 'Lowongan';
  const isDryRun = (currentMode === 'dry_run');

  // 1. Periksa status kredensial LinkedIn
  try {
    const credRes = await fetch('/api/settings/credentials');
    const credData = await credRes.json();
    if (!credData.linkedin_configured) {
      showToast('Akun LinkedIn belum terhubung. Silakan login terlebih dahulu.');
      openLinkedInModal();
      return;
    }
  } catch (e) {
    // Non-blocking fallback
  }

  // 2. Feedback visual langsung pada tombol
  let originalHtml = '';
  if (buttonEl) {
    originalHtml = buttonEl.innerHTML;
    buttonEl.disabled = true;
    buttonEl.innerHTML = '<span class="status-dot busy" style="width:6px;height:6px;margin-right:4px;"></span> Memproses...';
  }

  showToast('Memulai peramban otomatis...');
  const monitorCard = document.getElementById('monitor-card');
  const statusBadge = document.getElementById('monitor-status-badge');
  const stepDesc = document.getElementById('monitor-step-desc');

  if (monitorCard) {
    monitorCard.classList.add('active');
    monitorCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  if (statusBadge) {
    statusBadge.textContent = isDryRun ? 'Simulasi Berjalan...' : 'Mengirim Lamaran...';
    statusBadge.style.color = 'var(--brand-blue)';
  }
  if (stepDesc) {
    stepDesc.textContent = `Membuka dan mengisi: ${jobTitle}...`;
  }

  appendTerminalLog(`Memproses pengajuan mandiri: ${jobTitle} [Mode: ${isDryRun ? 'Simulasi (Dry Run)' : 'Kirim Langsung'}]...`, 'info');

  try {
    const res = await fetch('/api/jobs/easy-apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: jobId,
        dry_run: isDryRun
      })
    });
    const data = await res.json();

    if (data.success) {
      const platformName = data.platform || 'LinkedIn';
      if (data.status === 'submitted') {
        appendTerminalLog(`Sukses: Lamaran "${jobTitle}" berhasil terkirim via ${platformName}!`, 'success');
        showToast(`Lamaran berhasil dikirim via ${platformName}!`);
      } else {
        appendTerminalLog(`Sukses: Formulir ${platformName} terisi lengkap via Gemini AI. Bukti screenshot disimpan.`, 'success');
        showToast(`Simulasi selesai! Bukti screenshot ${platformName} telah dibuat.`);
      }
    } else {
      if (data.status === 'session_expired' || (data.error && (data.error.includes('kedaluwarsa') || data.error.includes('REDIRECTS')))) {
        window.isSessionExpired = true;
        await checkLinkedInStatus();
        appendTerminalLog(`Sesi kedaluwarsa: ${data.error}`, 'error');
        showToast('Sesi LinkedIn Anda telah kedaluwarsa. Silakan masuk kembali.');
        openLinkedInModal();
      } else if (data.status === 'external_apply_only') {
        appendTerminalLog(`Info: Lowongan ini mengarahkan ke portal eksternal (disimpan ke daftar).`, 'warn');
        showToast('Lowongan eksternal: Disimpan ke daftar lamaran.');
      } else {
        appendTerminalLog(`Pemberitahuan: ${data.message || data.error}`, 'warn');
        showToast(data.message || data.error || 'Pengisian formulir dilewati.');
      }
    }

    await loadJobs();
  } catch (err) {
    appendTerminalLog(`Gagal memproses lowongan: ${err.message}`, 'error');
    showToast('Kendala koneksi ke server lokal.');
  } finally {
    if (buttonEl) {
      buttonEl.disabled = false;
      buttonEl.innerHTML = originalHtml;
    }
  }
}

// ==========================================================================
// Screenshot Modal
// ==========================================================================
function openScreenshotModal(imgUrl, title) {
  const modal = document.getElementById('modal-screenshot');
  const img = document.getElementById('screenshot-view-img');
  const openLink = document.getElementById('screenshot-open-tab-btn');
  const subTitle = document.getElementById('modal-shot-subtitle');

  if (img) img.src = imgUrl;
  if (openLink) openLink.href = imgUrl;
  if (subTitle) subTitle.textContent = `Tangkapan layar formulir Easy Apply: ${title}`;

  modal?.classList.add('open');
}

function closeScreenshotModal() {
  document.getElementById('modal-screenshot')?.classList.remove('open');
}
