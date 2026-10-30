@echo off
REM Gera o executável Windows em dist\VoiceStudio\VoiceStudio.exe
setlocal
cd /d "%~dp0"

if not exist .venv (
    echo Criando ambiente virtual...
    py -3 -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error

echo Instalando dependencias...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements-dev.txt || goto :error

echo Executando testes...
python -m pytest tests -q || goto :error

echo Gerando icone...
python tools\make_icon.py || goto :error

echo Empacotando com PyInstaller...
pyinstaller VoiceStudio.spec --noconfirm --clean || goto :error

echo.
echo Pronto! Executavel: dist\VoiceStudio\VoiceStudio.exe
exit /b 0

:error
echo.
echo *** Falha no build ***
exit /b 1
