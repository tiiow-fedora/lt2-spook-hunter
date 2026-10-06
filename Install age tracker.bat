@echo off
rem Runs the server-age tracker every 10 minutes (Windows Task Scheduler). Put this next to
rem LT2SpookHunter.exe (or in the Python version's folder) and double-click it once.
cd /d "%~dp0"
if exist "%~dp0LT2SpookHunter.exe" (
  schtasks /Create /F /SC MINUTE /MO 10 /TN "LT2 server age tracker" /TR "\"%~dp0LT2SpookHunter.exe\" --tracker"
  start "" "%~dp0LT2SpookHunter.exe" --tracker
) else (
  schtasks /Create /F /SC MINUTE /MO 10 /TN "LT2 server age tracker" /TR "\"%~dp0run_tracker.bat\""
  call "%~dp0run_tracker.bat"
)
echo.
echo Done. The tracker now checks the server list every 10 minutes.
echo After a few hours, set "Only servers older than (h)" in the panel (6 is a good value).
echo To remove it later:  schtasks /Delete /TN "LT2 server age tracker" /F
pause
