@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"

set APP_NAME=invoice_uploader
set DIST_DIR=dist\%APP_NAME%
set PLAYWRIGHT_CACHE=%USERPROFILE%\AppData\Local\ms-playwright

echo [1/5] Installing build dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail

python -m pip install pyinstaller -r requirements.txt
if errorlevel 1 goto :fail

echo [2/5] Installing Playwright browser runtime...
python -m playwright install chromium
if errorlevel 1 goto :fail

echo [3/5] Cleaning old build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [4/5] Building executable from spec...
pyinstaller --noconfirm --clean invoice_uploader.spec
if errorlevel 1 goto :fail

echo [5/5] Copying Playwright runtime...
if exist "%PLAYWRIGHT_CACHE%" (
    xcopy "%PLAYWRIGHT_CACHE%" "%DIST_DIR%\ms-playwright\" /E /I /Y >nul
) else (
    echo Warning: Playwright runtime cache not found: %PLAYWRIGHT_CACHE%
)

echo.
echo Build complete.
echo Output folder: %DIST_DIR%
pause
exit /b 0

:fail
echo.
echo Build failed.
pause
exit /b 1
