@echo off
cd /d "%~dp0tracker"
pythonw lt2_tracker.py >> tracker.log 2>&1
