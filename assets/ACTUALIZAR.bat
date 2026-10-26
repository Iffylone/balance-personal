@echo off
setlocal
cd /d "%~dp0"
title Actualizar Sistema Contable Iffyware
echo ============================================
echo   Actualizando Sistema Contable Iffyware
echo ============================================
echo.

echo [1/5] Cerrando el programa si esta abierto...
taskkill /f /im SistContiffy.exe >nul 2>nul

echo [2/5] Respaldando tus datos...
if not exist "dist\contabilidad.db" (
    echo AVISO: no existe dist\contabilidad.db
    echo Si tus datos estan en otro lado, copia contabilidad.db a la carpeta dist y volve a ejecutar.
    pause
    exit /b 1
)
for /f %%i in ('powershell -nologo -command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%i
copy /y "dist\contabilidad.db" "dist\respaldo_%TS%.db" >nul
if %errorlevel% neq 0 (
    echo ERROR: no se pudo hacer el respaldo. No se continua.
    pause
    exit /b 1
)
echo       Respaldo creado: dist\respaldo_%TS%.db

echo [3/5] Verificando entorno de Python...
set NEEDVENV=0
if not exist "venv\Scripts\python.exe" set NEEDVENV=1
if %NEEDVENV%==0 (
    "venv\Scripts\python.exe" --version >nul 2>nul
    if errorlevel 1 set NEEDVENV=1
)
if %NEEDVENV%==1 (
    echo       Recreando entorno virtual...
    if exist venv rmdir /s /q venv
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: no se pudo crear el entorno. Verifica que Python este instalado con "Add Python to PATH".
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat

echo [4/5] Instalando PyInstaller...
python -m pip install pyinstaller
if errorlevel 1 (
    echo ERROR: fallo la instalacion de PyInstaller. Revisa tu conexion a internet.
    pause
    exit /b 1
)

echo [5/5] Generando el .exe nuevo...
python -m PyInstaller --noconfirm --onefile --noconsole --name "SistContiffy" --icon assets\icon.ico --add-data "assets;assets" main.py
if errorlevel 1 (
    echo ERROR: fallo la generacion del .exe. Mandame captura de esta ventana.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   LISTO
echo   Abri: dist\SistContiffy.exe
echo   Tus datos siguen en dist\contabilidad.db
echo   Respaldo: dist\respaldo_%TS%.db
echo ============================================
pause
