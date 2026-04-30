@echo off
setlocal enabledelayedexpansion

echo == RPG Token Generator ^| PyInstaller Build ==
echo.

:: -------------------------------------------------------
:: Pre-flight checks
:: -------------------------------------------------------
where pyinstaller >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: pyinstaller not found.
    echo        Run:  pip install pyinstaller
    pause & exit /b 1
)

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: python not found on PATH.
    pause & exit /b 1
)

:: -------------------------------------------------------
:: Clean previous build artefacts
:: -------------------------------------------------------
if exist build   rd /s /q build
if exist dist    rd /s /q dist

:: -------------------------------------------------------
:: PyInstaller
::   --onefile      single portable .exe
::   --windowed     no console window
::   --paths        lets PyInstaller's analyser find the panels package
::   --hidden-import PyQt6.QtSvg is imported inside a function so the
::                  static analyser misses it without this flag
:: -------------------------------------------------------
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "RPGTokenGenerator" ^
    --paths "Token Generator" ^
    --hidden-import "PyQt6.QtSvg" ^
    "Token Generator\main.py"

if %ERRORLEVEL% neq 0 (
    echo.
    echo Build FAILED — see output above.
    pause & exit /b 1
)

:: -------------------------------------------------------
:: Assemble release folder
::
:: dist\release\
::   RPG Token Generator.exe   <- the single executable
::   Backgrounds\              <- pre-generated backgrounds
::   Frames\                   <- pre-generated frames
::   Figures\                  <- empty; users drop images here
::   Tokens\                   <- empty; filled on first export
:: -------------------------------------------------------
set RELEASE=dist\release

if exist "%RELEASE%" rd /s /q "%RELEASE%"
mkdir "%RELEASE%"

move "dist\RPGTokenGenerator.exe" "%RELEASE%\RPG Token Generator.exe"

if exist "Token Generator\Backgrounds" (
    xcopy /E /I /Y "Token Generator\Backgrounds" "%RELEASE%\Backgrounds" >nul
    echo Copied Backgrounds\
)
if exist "Token Generator\Frames" (
    xcopy /E /I /Y "Token Generator\Frames" "%RELEASE%\Frames" >nul
    echo Copied Frames\
)
mkdir "%RELEASE%\Figures"
mkdir "%RELEASE%\Tokens"

:: Tidy up PyInstaller's intermediate files (optional but keeps repo clean)
rd /s /q build
del /q RPGTokenGenerator.spec 2>nul

echo.
echo -------------------------------------------------------
echo  Done!  Release folder:  %RELEASE%\
echo.
echo  Contents:
dir /b "%RELEASE%"
echo -------------------------------------------------------
echo.
echo  Zip the entire '%RELEASE%' folder and share it.
echo  Users just unzip and run "RPG Token Generator.exe".
pause
