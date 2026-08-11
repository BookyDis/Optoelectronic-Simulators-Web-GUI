@echo off
cd /d "%~dp0"

:: 1. Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

:: 2. Open the browser to your app's local address
start "" "http://127.0.0.1:5000"

:: 3. Run the Python web server silently in this background process
python app.py