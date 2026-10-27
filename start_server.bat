@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo =====================================================================
echo Starting PSNA 24h Hackathon Face Recognition (HTTP Mode)
echo Access URL: http://localhost:7010 or http://^<YOUR_SERVER_IP^>:7010
echo Tip: For client laptops over LAN to use their webcam without browser
echo security warnings, run start_server_https.bat instead.
echo =====================================================================
uvicorn app.main:app --host 0.0.0.0 --port 7010 --reload
pause
