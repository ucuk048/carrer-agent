# Career Agent — Autonomous LinkedIn Job Radar & Auto-Applier

Career Agent adalah platform otomatisasi pencarian kerja cerdas berbasis Python, Playwright, dan Google Gemini AI. Sistem ini memindai lowongan LinkedIn secara berkala, menghitung skor kesesuaian kualifikasi kandidat, dan mengisi formulir LinkedIn Easy Apply secara otomatis dengan mode tinjauan terkendali (*Human-in-the-loop*).

---

## Fitur Utama

1. **Pemindai Lowongan (Job Radar):**
   - Mengambil lowongan LinkedIn Easy Apply berdasarkan kategori keahlian, kata kunci spesifik, dan filter lokasi (misal: Makassar, Jakarta, Indonesia, Remote).
   - Melakukan deduplikasi otomatis agar lowongan yang sama tidak tersimpan ganda.

2. **Pengisian Formulir Otomatis (Easy Apply Engine):**
   - Menggunakan Playwright Chromium untuk mengotomasi alur formulir multilangkah LinkedIn Easy Apply.
   - Didukung oleh Google Gemini AI untuk menjawab pertanyaan seleksi kualifikasi (pengalaman, tools, gaji, domisili, visa) sesuai data diri pelamar.
   - Menyimpan tangkapan layar (*screenshot*) setiap tahap pengisian formulir sebagai bukti audit.

3. **Dua Mode Eksekusi yang Aman:**
   - **Mode Simulasi (Dry Run):** Mengisi seluruh pertanyaan formulir menggunakan AI dan mengambil screenshot bukti pada langkah terakhir tanpa menekan tombol kirim akhir.
   - **Mode Kirim Langsung (Live Apply):** Menyelesaikan pengisian formulir hingga pengajuan terkirim resmi ke LinkedIn Recruiter.

4. **Sinkronisasi Akun & Profil LinkedIn:**
   - Mengimpor nama lengkap, headline, lokasi, keahlian teknis, dan foto profil langsung dari akun LinkedIn yang terhubung.
   - Mengunduh otomatis CV resmi LinkedIn dalam format PDF ke penyimpanan lokal.

5. **Dukungan Portal ATS Eksternal:**
   - Mendeteksi dan mengisi otomatis formulir pada portal karir modern pihak ketiga (Ashby, Greenhouse, Lever).

6. **Dashboard Interaktif Berkinerja Tinggi:**
   - Antarmuka web modern dengan DataTables interaktif: pencarian instan, penomoran urut, filter kategori lowongan, filter lokasi kerja, serta aksi hapus massal (*batch delete*).
   - Bilah telemetri *Diagnostik Sistem* terintegrasi untuk memantau status online API dan latensi model Gemini.

---

## Arsitektur & Teknologi

- **Backend:** Python 3.10+ (menggunakan `http.server.ThreadingHTTPServer` standar tanpa framework berat).
- **Automasi Peramban:** Playwright Chromium headless/headful.
- **Kecerdasan Buatan:** Google Gemini API (model default: `gemini-3.5-flash-lite`).
- **Basis Data:** SQLite lokal (`database/career_agent.db`).
- **Frontend:** HTML5 semantik, CSS murni (desain standar Tier-1 light mode), JavaScript Vanilla, DataTables, jQuery.

---

## Prasyarat Sistem

Sebelum memasang proyek di komputer atau laptop lain, pastikan perangkat telah terpasang:

1. **Python 3.10 atau versi lebih baru**
   - Unduh dari situs resmi: [python.org](https://www.python.org/downloads/)
   - *Penting saat instalasi di Windows:* Centang opsi **"Add python.exe to PATH"**.
2. **Git**
   - Unduh dari: [git-scm.com](https://git-scm.com/)
3. **Google Gemini API Key**
   - Dapatkan kunci API gratis dari [Google AI Studio](https://aistudio.google.com/).

---

## Panduan Instalasi di Komputer / Laptop Lain (Lokal)

Ikuti langkah-langkah berikut secara berurutan pada terminal (PowerShell, Command Prompt, atau Terminal macOS/Linux):

### 1. Kloning Repositori
```bash
git clone https://github.com/username-anda/carrer-agent.git
cd carrer-agent
```

### 2. Buat & Aktifkan Virtual Environment Python

**Pada Windows:**
```powershell
python -m venv venv
.\venv\Scripts\activate
```

**Pada Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Pasang Dependensi Python
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Pasang Browser Chromium untuk Playwright
Playwright membutuhkan binary peramban Chromium untuk menjalankan automasi LinkedIn:
```bash
playwright install chromium
```

### 5. Konfigurasi File Lingkungan (.env)
Salin berkas `.env.example` menjadi `.env`:

**Pada Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**Pada Linux / macOS:**
```bash
cp .env.example .env
```

Buka file `.env` menggunakan editor teks (Notepad, VS Code, atau nano), lalu masukkan API key Gemini Anda:
```env
PORT=3001
GEMINI_API_KEY=masukkan_kunci_api_gemini_anda_di_sini
GEMINI_MODEL=gemini-3.5-flash-lite
MAX_JOBS_PER_BATCH=25
MAX_APPLICATION_DRAFTS_PER_DAY=10
```

### 6. Jalankan Server Aplikasi
```bash
python server.py
```

Setelah server aktif, terminal akan menampilkan:
```text
Career Agent server running at http://localhost:3001
Landing Page: http://localhost:3001/
Dashboard: http://localhost:3001/dashboard
```

Buka peramban favorit Anda dan akses:
- **Dashboard Utama:** [http://localhost:3001/dashboard](http://localhost:3001/dashboard)
- **Landing Page:** [http://localhost:3001/](http://localhost:3001/)

---

## Panduan Menghubungkan Akun LinkedIn

Untuk memproses Easy Apply, peramban automasi memerlukan sesi LinkedIn aktif Anda. Tersedia 2 metode:

### Metode 1: Login Interaktif Peramban (Paling Mudah)
1. Buka dashboard di `http://localhost:3001/dashboard`.
2. Klik tombol pill **LinkedIn: Memeriksa...** di sudut kanan atas.
3. Klik tombol **Buka Jendela Login Chromium (Rekomendasi)**.
   *(Di Windows, Anda juga dapat mengklik dua kali file `buka_login_linkedin.bat` di folder proyek).*
4. Jendela browser Chromium akan terbuka. Masuk ke akun LinkedIn Anda seperti biasa (termasuk verifikasi 2FA jika ada).
5. Setelah berhasil masuk ke feed LinkedIn, tutup jendela atau sistem akan mendeteksi sesi secara otomatis.
6. Profil, foto, keahlian, dan ringkasan CV Anda akan otomatis tersinkronisasi ke dashboard.

### Metode 2: Input Cookie Manual (`li_at`)
1. Buka LinkedIn di peramban harian Anda (Chrome / Edge).
2. Tekan tombol `F12` (atau Klik Kanan -> *Inspect*).
3. Buka tab **Application** -> **Cookies** -> `https://www.linkedin.com`.
4. Cari entri bernama **`li_at`**, lalu salin nilainya.
5. Pada modal koneksi LinkedIn di dashboard, buka bagian *Input Cookie Manual*, tempel nilai tersebut, lalu klik **Simpan Cookie**.

---

## Alur Pemakaian Sehari-hari

1. **Atur Data Diri:**
   - Klik tombol **Data Pelamar** di kanan atas dashboard untuk memastikan nomor telepon, pengalaman kerja, dan ekspektasi gaji Anda sudah sesuai.
2. **Pindai Lowongan (Job Radar):**
   - Pada panel **1. Pemindai Lowongan**, pilih kategori keahlian (misal: *Network Engineer*, *Software Engineer*), ketik lokasi target, dan pilih kuota pemindaian.
   - Klik **Pindai Lowongan LinkedIn**. Sistem akan mengumpulkan lowongan baru ke database radar lokal.
3. **Eksekusi Pengiriman Lamaran:**
   - Pada panel **2. Pengirim Lamaran Otomatis**, pilih mode:
     - Gunakan **Mode Simulasi (Dry Run)** untuk uji coba pengisian formulir tanpa pengiriman nyata.
     - Gunakan **Mode Kirim Langsung (Live Apply)** untuk langsung mengajukan lamaran ke perusahaan.
   - Tentukan kuota dan filter lokasi, lalu klik tombol **Mulai Pengiriman**.
4. **Periksa Hasil & Bukti Pengisian:**
   - Pada tabel **Daftar Lowongan & Riwayat**, klik tombol **Lihat Bukti** pada lowongan yang telah diproses untuk melihat screenshot formulir yang telah terisi.

---

## Struktur Direktori Proyek

```text
.
├── .env.example              # Template variabel lingkungan
├── .gitignore                # Pengecualian berkas rahasia & build
├── README.md                 # Dokumentasi proyek
├── requirements.txt          # Daftar dependensi pustaka Python
├── server.py                 # Server HTTP utama & routing REST API
├── linkedin_easy_apply.py    # Mesin automasi Playwright untuk LinkedIn Easy Apply
├── linkedin_manual_login.py  # Modul autentikasi, sinkronisasi profil & unduh CV
├── linkedin_scraper.py       # Pemindai lowongan publik LinkedIn
├── external_apply.py         # Automasi formulir portal karir ATS pihak ketiga
├── profile_extractor.py      # Ekstraktor teks resume dan profil kandidat
├── buka_login_linkedin.bat   # Skrip pembantu peluncur browser login di Windows
├── dashboard/                # Antarmuka dashboard pelamar kerja
│   ├── index.html            # Halaman utama dashboard
│   ├── dashboard.css         # Gaya visual standar Tier-1
│   └── dashboard.js          # Logika frontend, interaksi DataTables & API
├── landing-page/             # Halaman promosi & profil pengantar
│   ├── index.html            # Tampilan muka landing page
│   ├── styles.css            # Desain minimalis landing page
│   └── script.js             # Skrip interaktif landing page
├── database/                 # Berkas basis data SQLite lokal
│   ├── career_agent.db       # Database SQLite (dibuat otomatis)
│   └── schema.sql            # Skema tabel database
└── uploads/                  # Penyimpanan berkas lokal
    ├── applications/         # Screenshot bukti pengisian formulir
    ├── avatars/              # Foto profil LinkedIn kandidat
    └── resumes/              # File PDF CV resmi kandidat
```

---

## Batasan & Etika Penggunaan

- **Kendali Manusiawi:** Selalu tinjau profil dan preferensi sebelum menjalankan mode *Live Apply*.
- **Anti-Spam:** Sistem dilengkapi jeda waktu alami antar pengisian formulir guna mematuhi batas wajar penggunaan peramban.
- **Keamanan Kredensial:** Jangan pernah mengunggah berkas `.env`, folder `data/linkedin_browser_profile/`, atau cookie sesi ke repositori publik GitHub. Berkas-berkas sensitif tersebut telah dilindungi di dalam berkas `.gitignore`.

---

## Lisensi

Proyek ini dikembangkan untuk kebutuhan manajemen karir dan otomasi pencarian kerja mandiri. Bebas digunakan dan disesuaikan sesuai kebutuhan Anda.
