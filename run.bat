@echo off
title Telegram AI Assistant - Selobrow
cd /d "%~dp0"

echo ===================================================
echo     MEMULAI ASISTEN AI TELEGRAM (SELOBROW)
echo ===================================================

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment belum dibuat. Membuat .venv...
    python -m venv .venv
    echo [*] Menginstall dependensi...
    .\.venv\Scripts\pip install -r requirements.txt
)

echo [*] Menjalankan bot...
.\.venv\Scripts\python.exe bot.py
pause
