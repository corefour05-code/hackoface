@echo off
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat

pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

python software\stage_models.py
if errorlevel 1 goto :eof

pyinstaller software\build.spec --distpath software\dist --workpath software\_build\work --noconfirm

echo.
echo Build complete: software\dist\AttendanceApp\AttendanceApp.exe
pause
