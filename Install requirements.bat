@echo off
rem Python version only: installs the libraries the hunter needs. Double-click once.
cd /d "%~dp0"
py -m pip install -r requirements.txt || python -m pip install -r requirements.txt
echo.
echo Done. Now double-click "Start LT2 Spook Hunter.bat".
pause
