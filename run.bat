@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONFAULTHANDLER=1"
set "HF_HUB_DISABLE_PROGRESS_BARS=1"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "HF_HUB_DISABLE_XET=1"
if not defined QWEN_ASR_MODEL_PATH if exist "%~dp0models\Qwen3-ASR-1.7B\config.json" set "QWEN_ASR_MODEL_PATH=%~dp0models\Qwen3-ASR-1.7B"

if not exist ".venv\Scripts\python.exe" goto missing_venv
if /I "%~1"=="--check" goto startup_check

".venv\Scripts\python.exe" app.py
set "APP_EXIT_CODE=%ERRORLEVEL%"
if "%APP_EXIT_CODE%"=="0" exit /b 0

echo.
echo [ERROR] QwenASRDesktop exited with code %APP_EXIT_CODE%.
echo Check the application window and QwenASRDesktop.log for details.
pause
exit /b %APP_EXIT_CODE%

:startup_check
".venv\Scripts\python.exe" -c "import app; from src.main_window import MainWindow; print('QwenASRDesktop startup imports OK')"
exit /b %ERRORLEVEL%

:missing_venv
echo [ERROR] Virtual environment not found.
echo Run: powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
pause
exit /b 1
