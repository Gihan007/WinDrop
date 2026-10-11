@echo off
REM Uploads WinDrop to https://github.com/Gihan007/WinDrop and starts the first release build.
REM Needs Git for Windows: https://git-scm.com/download/win
cd /d "%~dp0"
git push origin main || goto :fail
git tag v1.0.0 2>nul
git push origin v1.0.0 || goto :fail
echo.
echo Uploaded! GitHub is now building WinDrop-Setup.exe (about 5 minutes).
echo Watch it here:  https://github.com/Gihan007/WinDrop/actions
echo Download here:  https://github.com/Gihan007/WinDrop/releases
start https://github.com/Gihan007/WinDrop/actions
pause
exit /b 0
:fail
echo.
echo Upload failed. Make sure Git is installed and you signed in to GitHub when asked.
pause
exit /b 1
