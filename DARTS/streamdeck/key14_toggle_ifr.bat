@echo off
REM Toggles live map IFR waypoints. Keep the map open in a browser.
set "BASE=http://localhost:8766"
curl -s -X POST "%BASE%/api/ui-command" -H "Content-Type: application/json" -d "{\"command\":\"toggle_ifr\"}"
echo.
timeout /t 2 >nul
