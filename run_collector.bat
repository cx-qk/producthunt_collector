@echo off
setlocal

cd /d "%~dp0"

echo Starting Product Hunt Collector...
echo.

uv run python fetch_producthunt.py

echo.
if errorlevel 1 (
  echo Product Hunt Collector failed. Check the message above.
) else (
  echo Product Hunt Collector finished successfully.
)

echo.
pause
