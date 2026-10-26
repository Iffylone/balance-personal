@echo off
title Generar ejecutable autonomo
echo Esto crea un .exe que no necesita Python instalado.
echo Ejecutalo despues de correr instalar.bat al menos una vez.
echo.
call venv\Scripts\activate.bat
pip install pyinstaller
pyinstaller --onefile --noconsole --name "SistContiffy" ^
    --icon assets\icon.ico ^
    --add-data "assets;assets" ^
    main.py
echo.
echo ============================================
echo El ejecutable quedo en la carpeta: dist\SistContiffy.exe
echo.
echo IMPORTANTE sobre tus datos:
echo La primera vez que abras el .exe se va a crear un archivo nuevo
echo "contabilidad.db" al lado del .exe (dentro de la carpeta dist).
echo Si ya tenias contabilidad.db de antes (de ejecutar.bat) y queres
echo seguir con esos mismos datos, copiala manualmente a la carpeta dist
echo ANTES de abrir el .exe por primera vez, reemplazando la que se cree.
echo Despues de esa primera vez, el .exe SIEMPRE lee y guarda en esa
echo misma contabilidad.db, sin importar cuantas veces lo cierres y
echo lo vuelvas a abrir.
echo ============================================
pause
