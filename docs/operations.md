# Operations Runbook

## Safety controls

- `AUTO_SUBMIT` harus selalu `false` pada fase awal.
- Gunakan satu candidate profile aktif per workflow execution.
- Tetapkan `MAX_JOBS_PER_BATCH` dan `MAX_APPLICATION_DRAFTS_PER_DAY`.
- Sediakan kill switch dengan menghentikan workflow aktif dan menonaktifkan credential eksternal.
- Semua tindakan eksternal harus membuat `audit_events`.

## Retry policy

Retry hanya untuk error transient seperti timeout, rate limit, dan temporary upstream failure. Jangan retry otomatis untuk validation error, permission error, CAPTCHA, atau ambiguous submission state.

Jika status submit tidak jelas, tandai sebagai `submission_unknown` dan minta verifikasi manusia. Jangan mencoba submit ulang secara buta.

## Quality gates

Sebelum draft dikirim untuk approval, validasi:

1. Semua klaim cover letter punya sumber di resume facts.
2. Tidak ada placeholder seperti `[COMPANY]` atau `[ACHIEVEMENT]`.
3. Job URL valid dan belum expired.
4. Tidak ada risk flag kritis.
5. Score dan alasan scoring tersedia.
6. Consent kandidat masih berlaku.

## Incident handling

Jika agent menghasilkan klaim palsu, menghitung score keliru, atau mengirim tindakan yang tidak diinginkan:

1. Matikan workflow terkait.
2. Simpan execution ID dan audit event.
3. Tandai aplikasi terdampak.
4. Cabut approval yang masih pending.
5. Perbaiki prompt, validator, atau data source.
6. Jalankan regression test sebelum re-enable.
