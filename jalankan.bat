@echo off
title Career Agent - Server
cd /d "%~dp0"

echo ===================================================================
echo Career Agent - Memulai Server Lokal
echo ===================================================================
echo.

REM 1. Verifikasi Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python tidak terdeteksi di sistem PATH.
    echo Silakan install Python 3.10+ dari python.org dan centang "Add to PATH".
    pause
    exit /b 1
)

REM 2. Gunakan venv jika ada
if exist "venv\Scripts\activate.bat" (
    echo Mengaktifkan virtual environment venv...
    call venv\Scripts\activate.bat
)

REM 3. Port default
set PORT=3001

REM 4. Buka dashboard di browser secara asynchronous
echo Membuka dashboard di browser: http://localhost:%PORT%/dashboard
start "" http://localhost:%PORT%/dashboard

REM 5. Jalankan server
echo Menjalankan Career Agent di port %PORT%...
echo Tekan Ctrl + C untuk menghentikan server.
echo ===================================================================
echo.

python server.py %PORT%

pause