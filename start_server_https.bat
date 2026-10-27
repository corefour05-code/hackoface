@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo =====================================================================
echo Starting PSNA 24h Hackathon Face Recognition (HTTPS Secure Mode)
echo This enables Client Laptop Webcams across the local area network.
echo Access URL: https://localhost:7011 or https://^<YOUR_SERVER_IP^>:7011
echo =====================================================================
uvicorn app.main:app --host 0.0.0.0 --port 7011 --ssl-keyfile key.pem --ssl-certfile cert.pem --reload
pause
