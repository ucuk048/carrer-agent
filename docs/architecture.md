# Arsitektur AI Career Agent

## Prinsip desain

Agent dipisahkan menjadi beberapa tahap kecil agar hasilnya dapat diperiksa dan mudah diulang. Model AI hanya mengusulkan tindakan dan menghasilkan teks; n8n tetap menjadi pengendali state, validasi, approval, dan audit trail.

## Alur MVP

```text
Candidate profile/CV
        |
        v
Normalize profile --> Collect jobs --> Deduplicate --> Score & explain
                                                   |
                                                   v
                               Generate tailored application draft
                                                   |
                                                   v
                                     Human approval gate
                                       /            \
                                  approved        rejected
                                     |              |
                             prepare application   save feedback
                             (no auto-submit)       and stop
```

## Data minimum

### Candidate profile

- Identitas kontak yang memang diperlukan.
- Lokasi dan preferensi kerja.
- Skill, pengalaman, pendidikan, bahasa, dan salary range.
- CV versi terbaru.
- Daftar perusahaan/role yang dikecualikan.

### Job record

- `source`, `external_id`, `url`, `title`, `company`.
- `location`, `employment_type`, `description`.
- `discovered_at`, `deadline`, `status`.
- `match_score` dan alasan scoring.

### Application record

- `job_id`, `candidate_id`, `cover_letter`.
- `resume_version`, `approval_status`, `submitted_at`.
- `notes`, `next_follow_up_at`.

## Guardrails

1. Jangan mengarang pengalaman, skill, pendidikan, sertifikasi, atau angka pencapaian.
2. Setiap draft harus menampilkan sumber fakta kandidat yang digunakan.
3. Tolak atau tandai lowongan dengan deskripsi tidak lengkap, scam indicators, atau permintaan pembayaran.
4. Batasi jumlah lowongan yang diproses per batch.
5. Simpan alasan rekomendasi agar kandidat dapat mengoreksi scoring.
6. Wajib approval manusia sebelum submit lamaran, mengirim pesan, atau membuat komitmen atas nama kandidat.
7. Simpan secret hanya di n8n Credentials/secret manager, bukan di JSON workflow atau git.

## Model scoring awal

Gunakan skor 0-100 yang terdiri dari:

- 40% kecocokan skill wajib.
- 20% kecocokan senioritas dan tahun pengalaman.
- 15% kecocokan lokasi/work arrangement.
- 15% kecocokan domain/industri.
- 10% kecocokan kompensasi dan preferensi.

Skor bukan keputusan otomatis. Tampilkan juga `missing_requirements`, `evidence`, dan `confidence`.

