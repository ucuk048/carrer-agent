const menuToggle = document.querySelector('.menu-toggle');
const nav = document.querySelector('.primary-nav');
menuToggle?.addEventListener('click', () => {
  const open = nav.classList.toggle('open');
  menuToggle.setAttribute('aria-expanded', String(open));
});
document.querySelectorAll('.primary-nav a').forEach((link) => link.addEventListener('click', () => {
  nav.classList.remove('open');
  menuToggle?.setAttribute('aria-expanded', 'false');
}));

const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
  if (entry.isIntersecting) { entry.target.classList.add('is-visible'); observer.unobserve(entry.target); }
}), { threshold: 0.05, rootMargin: '120px 0px' });
document.querySelectorAll('.reveal').forEach((element) => observer.observe(element));



// ==========================================================================
// Career Agent — LinkedIn Auth Controller & Auto-Sync
// ==========================================================================
let loginPollTimer = null;

function showToast(message, duration = 3500) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = message;
  toast.style.display = 'flex';
  setTimeout(() => {
    toast.style.display = 'none';
  }, duration);
}

function openLinkedInModal() {
  const modal = document.getElementById('modal-linkedin-login');
  if (!modal) return;
  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
}

function closeLinkedInModal() {
  const modal = document.getElementById('modal-linkedin-login');
  if (!modal) return;
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  if (loginPollTimer) {
    clearInterval(loginPollTimer);
    loginPollTimer = null;
  }
}

// Bind all LinkedIn Login trigger buttons
document.querySelectorAll('.btn-trigger-linkedin-login').forEach((btn) => {
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    openLinkedInModal();
  });
});

function switchLoginTab(tab) {
  const tabs = ['browser', 'credentials', 'cookie'];
  tabs.forEach((t) => {
    const btn = document.getElementById(`tab-btn-${t}`);
    const content = document.getElementById(`tab-content-${t}`);
    if (t === tab) {
      btn?.classList.add('active');
      btn?.setAttribute('aria-selected', 'true');
      if (content) content.style.display = 'block';
    } else {
      btn?.classList.remove('active');
      btn?.setAttribute('aria-selected', 'false');
      if (content) content.style.display = 'none';
    }
  });
}

function setLiveIndicator(active, statusText = '', detailText = '') {
  const card = document.getElementById('login-live-indicator');
  const sTitle = document.getElementById('live-progress-status');
  const sDetail = document.getElementById('live-progress-detail');
  if (!card) return;
  if (active) {
    card.style.display = 'flex';
    if (sTitle && statusText) sTitle.textContent = statusText;
    if (sDetail && detailText) sDetail.textContent = detailText;
  } else {
    card.style.display = 'none';
  }
}

async function startBrowserLogin() {
  const launchBtn = document.getElementById('btn-launch-browser-login');
  if (launchBtn) launchBtn.disabled = true;

  setLiveIndicator(true, 'Membuka peramban Chromium...', 'Silakan tunggu, jendela peramban sedang disiapkan.');

  try {
    const res = await fetch('/api/linkedin/manual-login/start', { method: 'POST' });
    const data = await res.json();

    setLiveIndicator(true, 'Peramban Siap', data.message || 'Silakan masukkan akun LinkedIn Anda di jendela yang muncul.');

    // Polling status proses login
    loginPollTimer = setInterval(async () => {
      try {
        const sRes = await fetch('/api/linkedin/manual-login/status');
        const sData = await sRes.json();

        if (sData.message) {
          const detail = document.getElementById('live-progress-detail');
          if (detail) detail.textContent = sData.message;
        }

        if (sData.status === 'completed') {
          clearInterval(loginPollTimer);
          loginPollTimer = null;
          setLiveIndicator(true, 'Login & Profil Terhubung!', 'Mengalihkan ke Dashboard Career Agent...');
          showToast('Login LinkedIn berhasil! Mengarahkan ke Data Pelamar...');
          setTimeout(() => {
            window.location.href = '/dashboard?editProfile=true';
          }, 1000);
        } else if (sData.status === 'timeout' || sData.status === 'error') {
          clearInterval(loginPollTimer);
          loginPollTimer = null;
          setLiveIndicator(false);
          if (launchBtn) launchBtn.disabled = false;
          showToast(sData.message || 'Waktu login habis atau peramban ditutup.');
        }
      } catch (err) {
        // Silent non-blocking poll error
      }
    }, 1500);
  } catch (err) {
    setLiveIndicator(false);
    if (launchBtn) launchBtn.disabled = false;
    showToast('Kendala jaringan saat meluncurkan peramban login.');
  }
}

async function cancelInteractiveLogin() {
  if (loginPollTimer) {
    clearInterval(loginPollTimer);
    loginPollTimer = null;
  }
  setLiveIndicator(false);
  const launchBtn = document.getElementById('btn-launch-browser-login');
  if (launchBtn) launchBtn.disabled = false;

  try {
    await fetch('/api/linkedin/manual-login/cancel', { method: 'POST' });
  } catch (e) {}

  showToast('Proses login dibatalkan.');
}

async function submitCredentialsLogin(event) {
  event.preventDefault();
  const email = document.getElementById('li-login-email')?.value.trim();
  const password = document.getElementById('li-login-password')?.value.trim();
  const submitBtn = document.getElementById('btn-submit-cred');

  if (!email || !password) {
    showToast('Email dan kata sandi wajib diisi.');
    return;
  }

  if (submitBtn) submitBtn.disabled = true;
  setLiveIndicator(true, 'Meluncurkan Peramban...', 'Mengisi kredensial akun secara otomatis ke LinkedIn...');

  try {
    const res = await fetch('/api/linkedin/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    const data = await res.json();

    if (!res.ok) {
      setLiveIndicator(false);
      if (submitBtn) submitBtn.disabled = false;
      showToast(data.error || 'Gagal memulai otentikasi kredensial.');
      return;
    }

    loginPollTimer = setInterval(async () => {
      try {
        const sRes = await fetch('/api/linkedin/manual-login/status');
        const sData = await sRes.json();

        if (sData.message) {
          const detail = document.getElementById('live-progress-detail');
          if (detail) detail.textContent = sData.message;
        }

        if (sData.status === 'completed') {
          clearInterval(loginPollTimer);
          loginPollTimer = null;
          setLiveIndicator(true, 'Login & Profil Terhubung!', 'Mengalihkan ke Dashboard...');
          showToast('Login LinkedIn berhasil! Mengarahkan ke Data Pelamar...');
          setTimeout(() => {
            window.location.href = '/dashboard?editProfile=true';
          }, 1000);
        } else if (sData.status === 'timeout' || sData.status === 'error') {
          clearInterval(loginPollTimer);
          loginPollTimer = null;
          setLiveIndicator(false);
          if (submitBtn) submitBtn.disabled = false;
          showToast(sData.message || 'Login terhenti atau gagal diverifikasi.');
        }
      } catch (err) {}
    }, 1500);
  } catch (err) {
    setLiveIndicator(false);
    if (submitBtn) submitBtn.disabled = false;
    showToast('Kendala jaringan saat otentikasi.');
  }
}

async function submitCookieLogin(event) {
  event.preventDefault();
  const cookieInput = document.getElementById('li-cookie-input');
  const cookieVal = cookieInput?.value.trim();
  const submitBtn = document.getElementById('btn-submit-cookie');

  if (!cookieVal) {
    showToast('Mohon masukkan nilai cookie li_at.');
    return;
  }

  if (submitBtn) submitBtn.disabled = true;
  setLiveIndicator(true, 'Menyinkronkan Sesi & Profil...', 'Membaca data lengkap dari LinkedIn...');

  try {
    const res = await fetch('/api/profile/sync-linkedin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ li_at: cookieVal })
    });
    const data = await res.json();

    if (res.ok && data.success) {
      setLiveIndicator(true, 'Profil Berhasil Disinkronkan!', 'Mengalihkan ke Dashboard...');
      showToast('Profil LinkedIn berhasil terhubung! Mengarahkan ke Data Pelamar...');
      setTimeout(() => {
        window.location.href = '/dashboard?editProfile=true';
      }, 1000);
    } else {
      setLiveIndicator(false);
      if (submitBtn) submitBtn.disabled = false;
      showToast(data.error || 'Gagal menyinkronkan profil via cookie.');
    }
  } catch (err) {
    setLiveIndicator(false);
    if (submitBtn) submitBtn.disabled = false;
    showToast('Kendala jaringan saat menghubungkan cookie.');
  }
}
