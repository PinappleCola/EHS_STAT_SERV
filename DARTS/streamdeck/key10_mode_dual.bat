@echo off
REM Switches DARTS to DUAL receiver mode and restarts both receivers.
set "BASE=http://localhost:8766"
curl -s -X POST "%BASE%/api/rx-config" -H "Content-Type: application/json" -d "{\"rx_mode\":\"DUAL\",\"restart\":\"BOTH\"}"
echo.
timeout /t 2 >nul
