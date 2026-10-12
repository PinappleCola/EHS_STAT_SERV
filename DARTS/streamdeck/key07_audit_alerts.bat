@echo off
REM Shows any currently active audit alerts.
set "BASE=http://localhost:8766"
curl -s "%BASE%/api/audit-alerts"
echo.
pause
