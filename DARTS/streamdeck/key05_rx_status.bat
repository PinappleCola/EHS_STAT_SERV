@echo off
REM Shows whether receiver A/B is connected and how fresh the data is.
set "BASE=http://localhost:8766"
curl -s "%BASE%/api/rx-status"
echo.
pause
