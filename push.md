# Panduan Lengkap Push Proyek ke GitHub (carrer-agent)

Panduan ini berisi instruksi langkah-demi-langkah untuk mempublikasikan proyek **carrer-agent** dari folder lokal `D:\Tools\AIC\n8n\eca-git` ke repositori GitHub Anda.

---

## Langkah 1: Buat Repositori Baru di GitHub

1. Buka peramban dan masuk ke akun GitHub Anda: [github.com](https://github.com/).
2. Buat repositori baru di [github.com/new](https://github.com/new).
3. Isi kolom:
   - **Repository name:** `carrer-agent`
   - **Description:** `Autonomous LinkedIn Job Radar & Auto-Applier with Google Gemini AI` (opsional)
   - **Visibility:** Pilih **Public** (jika ingin open source) atau **Private**.
4. **PENTING:**
   - **JANGAN CENTANG** *Add a README file*.
   - **JANGAN CENTANG** *Add .gitignore*.
   - **JANGAN CENTANG** *Choose a license*.
   *(Folder lokal kita sudah memiliki README.md dan .gitignore yang lengkap).*
5. Klik tombol hijau **Create repository**.

---

## Langkah 2: Buka Terminal di Folder Bersih

Buka **PowerShell** atau **Terminal**, lalu arahkan ke folder `D:\Tools\AIC\n8n\eca-git`:

```powershell
cd D:\Tools\AIC\n8n\eca-git
```

---

## Langkah 3: Konfigurasi Identitas Git (Jika Belum Pernah)

Jika ini pertama kali Anda menggunakan Git di laptop ini, atur nama dan email GitHub Anda:

```bash
git config --global user.name "Nama Anda"
git config --global user.email "email-github-anda@example.com"
```

---

## Langkah 4: Siapkan & Rekam Berkas (Stage & Commit)

Jalankan perintah berikut untuk merekam semua berkas proyek yang sudah bersih:

```bash
# Tambahkan seluruh berkas ke staging
git add .

# Rekam commit pertama
git commit -m "feat: initial release carrer-agent"

# Pastikan nama branch utama adalah 'main'
git branch -M main
```

---

## Langkah 5: Hubungkan ke Repositori GitHub

Hubungkan repositori lokal Anda ke URL repositori GitHub yang baru dibuat:

```bash
# Ganti USERNAME dengan nama pengguna GitHub Anda
git remote add origin https://github.com/USERNAME/carrer-agent.git
```

*Tips: Jika muncul pesan `error: remote origin already exists`, jalankan:*
```bash
git remote set-url origin https://github.com/USERNAME/carrer-agent.git
```

---

## Langkah 6: Unggah (Push) ke GitHub

Kirim seluruh kode proyek ke GitHub:

```bash
git push -u origin main
```

Saat diminta autentikasi:
- **Username:** Masukkan username GitHub Anda.
- **Password:** Masukkan **Personal Access Token (PAT)** GitHub Anda *(bukan password akun biasa)*.
  - Cara membuat token: Buka GitHub -> **Settings** -> **Developer Settings** -> **Personal Access Tokens (Tokens classic)** -> **Generate new token** -> centang cakupan `repo` -> salin token yang muncul.

---

## Cara Melakukan Update Kode di Masa Depan

Jika di kemudian hari Anda melakukan perubahan kode dan ingin memperbarui repositori GitHub:

```bash
cd D:\Tools\AIC\n8n\eca-git
git add .
git commit -m "update: deskripsi perubahan kode"
git push
```
