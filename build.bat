@echo off
:: ─────────────────────────────────────────────────────────────
:: build.bat — Builds Study Companion (Electron + Python)
:: Double-click to build for Windows
:: ─────────────────────────────────────────────────────────────
setlocal
echo.
echo  ===================================
echo   Study Companion — Build Script
echo  ===================================
echo.

:: ── Step 1: Build Python backend into exe ─────────────────────
echo  [1/4] Building Python backend...
pip install pyinstaller --quiet
pyinstaller app_build.spec --noconfirm --distpath dist_python
if errorlevel 1 (
    echo  ERROR: Python build failed.
    pause & exit /b 1
)
echo  Done.
echo.

:: ── Step 2: Install Electron dependencies ─────────────────────
echo  [2/4] Installing Electron dependencies...
cd electron
npm install --silent
if errorlevel 1 (
    echo  ERROR: npm install failed.
    pause & exit /b 1
)
echo  Done.
echo.

:: ── Step 3: Build Electron app ────────────────────────────────
echo  [3/4] Building Electron app...
npm run build-win
if errorlevel 1 (
    echo  ERROR: Electron build failed.
    pause & exit /b 1
)
cd ..
echo  Done.
echo.

echo  ===================================
echo   BUILD COMPLETE!
echo  ===================================
echo.
echo  Your installer is in:
echo    dist_electron\StudyCompanion Setup.exe
echo.
echo  Students just run that one installer file.
echo  Nothing else needed!
echo.
pause
