@echo off
REM Builds dist\WinDrop.exe on your own Windows PC.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller==6.10.0
pyinstaller --noconfirm --onefile --windowed --name WinDrop --icon assets\icon.ico --add-data "assets\icon.ico;assets" src\app.py
echo.
echo Done. Your app is at dist\WinDrop.exe
pause
