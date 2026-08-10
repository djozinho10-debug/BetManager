@echo off
setlocal
cd /d "%~dp0"
title BetManager Professional

echo.
echo ============================================
echo       BETMANAGER PROFESSIONAL
echo ============================================
echo.

where py >nul 2>&1
if errorlevel 1 (
  echo Python Launcher nao foi encontrado.
  echo Instale o Python e marque a opcao "Add Python to PATH".
  pause
  exit /b 1
)

echo [1/3] Conferindo dependencias Python...
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Falha ao instalar dependencias Python.
  pause
  exit /b 1
)

echo.
echo [2/3] Conferindo OCR Tesseract...
set "TESSFOUND="
where tesseract >nul 2>&1 && set "TESSFOUND=1"
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "TESSFOUND=1"
if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" set "TESSFOUND=1"
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" set "TESSFOUND=1"

if not defined TESSFOUND (
  echo Tesseract nao encontrado. Tentando instalar automaticamente com WinGet...
  where winget >nul 2>&1
  if not errorlevel 1 (
    winget install --id tesseract-ocr.tesseract --exact --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
      echo Primeira opcao nao funcionou. Tentando pacote alternativo...
      winget install --id UB-Mannheim.TesseractOCR --exact --accept-package-agreements --accept-source-agreements
    )
  ) else (
    echo.
    echo O WinGet nao esta disponivel neste Windows.
    echo Instale o Tesseract OCR e depois execute este arquivo novamente.
    echo Site/documentacao: tesseract-ocr.github.io
    pause
    exit /b 1
  )
)

if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe"
if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" set "TESSERACT_CMD=C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" set "TESSERACT_CMD=%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"

echo.
echo [3/3] Abrindo BetManager...
py -m streamlit run app.py
pause
