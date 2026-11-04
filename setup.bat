@echo off
rem Windows without make: double-click setup.bat (= make setup), or run `setup.bat <command>` e.g. `setup.bat doctor`.
set "CMD=%*"
if "%CMD%"=="" set "CMD=setup"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" %CMD%
if "%~1"=="" pause
