@echo off
REM Opens the DARTS live grid (table view) in your default browser.
set "BASE=http://localhost:8766"
start "" "%BASE%/grid"
