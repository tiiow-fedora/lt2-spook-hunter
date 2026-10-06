@echo off
rem Windows: run the server-age tracker every 10 minutes with Task Scheduler.
rem Then set  "tracker": {"file": "tracker/alive.json"}  in config.json.
set D=%~dp0
schtasks /Create /F /SC MINUTE /MO 10 /TN "LT2 server age tracker" /TR "\"%D%..\run_tracker.bat\""
echo Installed. It writes %D%alive.json every 10 minutes.
pause
