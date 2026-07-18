@echo off
echo Building TileDo.exe ...
py -3.12 -m PyInstaller --onefile --windowed --icon icon.ico --name TileDo tiledo.py
echo.
echo Done! Find TileDo.exe in the dist\ folder.
pause
