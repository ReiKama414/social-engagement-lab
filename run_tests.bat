@echo off
title Social Engagement Lab - Automated Tests
echo ========================================================
echo   Running Backend and Playwright Automation Tests
echo ========================================================
cd /d "%~dp0"
call backend\venv\Scripts\activate.bat
echo [1/3] Running API Core Integration Tests...
python -m pytest -v backend\tests\test_api.py
echo.
echo [2/3] Running Playwright E2E Browser Automation Tests...
python -m pytest -v backend\tests\test_playwright.py
echo.
echo [3/3] Running Deep Architecture, Security & Scale QA Suite...
python -m pytest -v backend\tests\test_qa_suite.py
echo ========================================================
echo   Test Execution Complete!
echo ========================================================
pause
