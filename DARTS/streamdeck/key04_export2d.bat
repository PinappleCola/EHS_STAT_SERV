@echo off
REM Saves the 2D trail export (GeoJSON) to your Downloads folder.
set "BASE=http://localhost:8766"
set "OUT=%USERPROFILE%\Downloads\darts_export2d.geojson"
curl -s "%BASE%/api/trails/export.geojson" -o "%OUT%"
echo Saved to %OUT%
timeout /t 2 >nul
