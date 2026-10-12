@echo off
REM Restarts receiver B without changing the receiver mode.
set "BASE=http://localhost:8766"
curl -s -X POST "%BASE%/api/rx-config" -H "Content-Type: application/json" -d "{\"restart\":\"B\"}"
echo.
timeout /t 2 >nul
