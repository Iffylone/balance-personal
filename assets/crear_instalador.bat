@echo off
chcp 65001 >nul
rem ==== Crea Instalador_SistContiffy.exe (para instalar el sistema en otras PCs) ====
rem Requisitos: haber generado dist\SistContiffy.exe (con generar_exe.bat o ACTUALIZAR.bat)
rem             y tener instalado NSIS (gratis): https://nsis.sourceforge.io/Download
cd /d "%~dp0"
if not exist "dist\SistContiffy.exe" (
  echo No existe dist\SistContiffy.exe. Primero ejecuta generar_exe.bat
  pause & exit /b 1
)
set MAKENSIS=
if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set MAKENSIS=%ProgramFiles(x86)%\NSIS\makensis.exe
if exist "%ProgramFiles%\NSIS\makensis.exe" set MAKENSIS=%ProgramFiles%\NSIS\makensis.exe
if "%MAKENSIS%"=="" (
  echo No se encontro NSIS. Instalalo desde https://nsis.sourceforge.io/Download y volve a ejecutar este archivo.
  pause & exit /b 1
)
copy /y "dist\SistContiffy.exe" "instalador\SistContiffy.exe" >nul
cd instalador
"%MAKENSIS%" instalador.nsi
if errorlevel 1 ( echo Fallo la creacion del instalador. & pause & exit /b 1 )
move /y "Instalador_SistContiffy.exe" ".." >nul
cd ..
echo.
echo Listo: Instalador_SistContiffy.exe quedo en esta carpeta.
pause
