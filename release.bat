@echo off
REM Gera o build, empacota e publica a release no GitHub (o app instalado encontra e instala sozinho).
REM Antes: aumente APP_VERSION em utils\paths.py e faça commit/push.
REM Uso: release.bat "Notas desta versão"
setlocal
cd /d "%~dp0"

call build.bat || goto :error
call .venv\Scripts\activate.bat || goto :error
python tools\release.py --publish --notes "%~1" || goto :error

echo.
echo Release publicada.
exit /b 0

:error
echo.
echo *** Falha na release ***
exit /b 1
