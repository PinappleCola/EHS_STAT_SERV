@echo off
REM Switches DARTS to single-receiver mode B and restarts receiver B.
set "BASE=http://localhost:8766"
curl -s -X POST "%BASE%/api/rx-config" -H "Content-Type: application/json" -d "{\"rx_mode\":\"B\",\"restart\":\"B\"}"
echo.
timeout /t 2 >nul
