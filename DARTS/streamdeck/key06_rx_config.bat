@echo off
REM Shows the current receiver mode (A / B / DUAL) and port config.
set "BASE=http://localhost:8766"
curl -s "%BASE%/api/rx-config"
echo.
pause
