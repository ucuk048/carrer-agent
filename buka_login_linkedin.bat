@echo off
chcp 65001 >nul
title Career Agent - Login LinkedIn Interaktif
cd /d "%~dp0"

echo ===================================================================
echo Career Agent LinkedIn Browser Login
echo ===================================================================
echo Membuka jendela peramban Chromium di layar Anda...
echo Silakan masukkan email dan password LinkedIn Anda pada jendela
echo peramban yang muncul, atau selesaikan verifikasi jika diminta.
echo 
echo Sesi akun Anda akan otomatis tersimpan setelah masuk ke LinkedIn.
echo ===================================================================
echo.

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python linkedin_manual_login.py --fresh

echo.
echo ===================================================================
echo Proses selesai. Silakan periksa kembali dashboard Career Agent.
echo ===================================================================
pause

