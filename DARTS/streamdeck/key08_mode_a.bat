@echo off
REM Switches DARTS to single-receiver mode A and restarts receiver A.
set "BASE=http://localhost:8766"
curl -s -X POST "%BASE%/api/rx-config" -H "Content-Type: application/json" -d "{\"rx_mode\":\"A\",\"restart\":\"A\"}"
echo.
timeout /t 2 >nul
