@echo off
cd /d %~dp0
python scripts\sglde_sammeln.py %*
if errorlevel 1 goto ende
python scripts\sglde_webseite.py --vorschau
:ende
pause
