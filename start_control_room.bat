@echo off
rem VANI Persona Service control room: double-click, then use the browser tab that opens.
cd /d "%~dp0"
echo Starting the VANI Persona Service on http://localhost:8080 ... (close this window to stop it)
start "" /b cmd /c "timeout /t 12 >nul & start http://localhost:8080"
".venv\Scripts\python.exe" -m uvicorn service.app:app --port 8080
pause
