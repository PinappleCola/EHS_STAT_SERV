@echo off
REM Toggles live map VFR waypoints. Keep the map open in a browser.
set "BASE=http://localhost:8766"
curl -s -X POST "%BASE%/api/ui-command" -H "Content-Type: application/json" -d "{\"command\":\"toggle_vfr\"}"
echo.
timeout /t 2 >nul
