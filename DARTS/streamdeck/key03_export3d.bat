@echo off
REM Saves the 3D trail export (Kepler.gl GeoJSON) to your Downloads folder.
set "BASE=http://localhost:8766"
set "OUT=%USERPROFILE%\Downloads\darts_export3d.geojson"
curl -s "%BASE%/api/trails/export3d.geojson" -o "%OUT%"
echo Saved to %OUT%
timeout /t 2 >nul
