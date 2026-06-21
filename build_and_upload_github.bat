@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

cd /d "%~dp0"

if /I "%~1"=="--help" goto :help
if /I "%~1"=="/?" goto :help

echo.
echo === Instagram to Eagle: build exe and upload to GitHub ===
echo Repo: %CD%
echo.

where py >nul 2>nul || goto :missing_py
where git >nul 2>nul || goto :missing_git

git rev-parse --is-inside-work-tree >nul 2>nul || goto :not_repo

for /f "delims=" %%R in ('git remote get-url origin 2^>nul') do set "ORIGIN_URL=%%R"
if not defined ORIGIN_URL goto :missing_origin

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "CURRENT_BRANCH=%%B"
if not defined CURRENT_BRANCH set "CURRENT_BRANCH=master"

echo GitHub remote: %ORIGIN_URL%
echo Branch: %CURRENT_BRANCH%
echo.

echo [1/4] Running tests...
py -m pytest -q
if errorlevel 1 goto :tests_failed

echo.
echo [2/4] Building exe package...
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\build_exe.ps1" %*
if errorlevel 1 goto :build_failed

set "EXE_PATH=%CD%\dist\Instagram to Eagle\Instagram to Eagle.exe"
if not exist "%EXE_PATH%" goto :missing_exe

echo.
echo Build complete:
echo "%EXE_PATH%"
echo.

echo [3/4] Checking git status...
git status --short
if errorlevel 1 goto :git_failed

set "HAS_CHANGES="
for /f "delims=" %%S in ('git status --porcelain') do (
    set "HAS_CHANGES=1"
)

if defined HAS_CHANGES (
    echo.
    echo Uncommitted changes were found.
    echo Note: build/, dist/, config.json, tools/*.exe, and .tmp/ are ignored by git.
    set /p COMMIT_NOW="Commit these changes before upload? [y/N]: "
    if /I "!COMMIT_NOW!"=="Y" (
        set /p COMMIT_MESSAGE="Commit message: "
        if not defined COMMIT_MESSAGE set "COMMIT_MESSAGE=Update app package"
        git add -A
        if errorlevel 1 goto :git_failed
        git commit -m "!COMMIT_MESSAGE!"
        if errorlevel 1 goto :git_failed
    ) else (
        echo.
        echo Upload stopped because the worktree still has uncommitted changes.
        echo Commit or discard them, then run this bat again.
        goto :failed
    )
)

echo.
echo [4/4] Uploading committed changes to GitHub...
git push origin "%CURRENT_BRANCH%"
if errorlevel 1 goto :push_failed

echo.
echo Done.
echo GitHub: %ORIGIN_URL%
echo EXE: "%EXE_PATH%"
goto :success

:help
echo Usage:
echo   build_and_upload_github.bat
echo.
echo What it does:
echo   1. Runs: py -m pytest -q
echo   2. Runs: scripts\build_exe.ps1
echo   3. Optionally commits uncommitted git changes
echo   4. Pushes the current branch to origin
echo.
echo Extra arguments are passed to scripts\build_exe.ps1, for example:
echo   build_and_upload_github.bat -ForceCloseRunningApp
exit /b 0

:missing_py
echo ERROR: Python launcher "py" was not found.
goto :failed

:missing_git
echo ERROR: git was not found.
goto :failed

:not_repo
echo ERROR: This folder is not a git repository.
goto :failed

:missing_origin
echo ERROR: git remote "origin" was not found.
goto :failed

:tests_failed
echo ERROR: Tests failed. Build and upload stopped.
goto :failed

:build_failed
echo ERROR: Exe build failed.
goto :failed

:missing_exe
echo ERROR: Build finished, but the exe was not found:
echo "%EXE_PATH%"
goto :failed

:git_failed
echo ERROR: Git command failed.
goto :failed

:push_failed
echo ERROR: GitHub upload failed.
goto :failed

:failed
echo.
echo Failed.
pause
exit /b 1

:success
echo.
pause
exit /b 0
