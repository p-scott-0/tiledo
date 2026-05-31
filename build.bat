@echo off
echo Building TileDo.exe ...
py -m PyInstaller --onefile --windowed --name TileDo tiledo.py
echo.
echo Done! Find TileDo.exe in the dist\ folder.
pause
