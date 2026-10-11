@echo off
REM Builds dist\WinDrop.exe on your own Windows PC.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller==6.10.0
if not exist vendor\aria2\aria2c.exe (
  echo Downloading aria2 torrent engine...
  powershell -NoProfile -Command "Invoke-WebRequest 'https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip' -OutFile aria2.zip; if ((Get-FileHash aria2.zip -Algorithm SHA256).Hash -ne '67D015301EEF0B612191212D564C5BB0A14B5B9C4796B76454276A4D28D9B288') { throw 'aria2 integrity check failed' }; Expand-Archive -Force aria2.zip aria2tmp; New-Item -ItemType Directory -Force vendor\aria2 | Out-Null; Get-ChildItem aria2tmp -Recurse -Include aria2c.exe,COPYING,LICENSE.OpenSSL | Copy-Item -Destination vendor\aria2"
)
pyinstaller --noconfirm --onefile --windowed --name WinDrop --icon assets\icon.ico --add-data "assets\icon.ico;assets" --add-data "vendor\aria2;aria2" src\app.py
echo.
echo Done. Your app is at dist\WinDrop.exe
pause
