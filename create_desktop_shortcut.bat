@echo off
title Create Desktop Shortcut
echo ========================================================
echo   Creating Windows Desktop Shortcut for Social Lab
echo ========================================================
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [Environment]::GetFolderPath('Desktop'); $shortcut = $ws.CreateShortcut($desktop + '\Social Engagement Lab.lnk'); $shortcut.TargetPath = '%~dp0start.bat'; $shortcut.WorkingDirectory = '%~dp0'; $shortcut.Description = 'Social Engagement Automation Lab One-Click Launcher'; $shortcut.Save()"

echo.
echo  [SUCCESS] Desktop Shortcut created!
echo  Check your Windows Desktop for "Social Engagement Lab.lnk"
echo ========================================================
pause
