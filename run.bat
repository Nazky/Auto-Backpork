@echo off
setlocal enabledelayedexpansion

:: ============================================
:: Auto-Backpork GUI - Windows Launcher
:: ============================================

echo ======================================
echo Auto-Backpork GUI - Windows Launcher
echo ======================================

:: --------------------------------------------------
:: Check if quick launch is possible
:: --------------------------------------------------
if not exist "venv\Scripts\activate.bat" goto setup
if not exist "venv\Scripts\python.exe" goto setup

:: Quick test that essential modules are present
venv\Scripts\python.exe -c "import customtkinter, PIL, py7zr, rarfile, _tkinter" >nul 2>&1
if %errorlevel% neq 0 goto setup

:: Environment is ready - quick launch
echo Existing environment found. Launching directly...
call venv\Scripts\activate.bat
goto launch

:: --------------------------------------------------
:: Setup mode - first run or missing dependencies
:: --------------------------------------------------
:setup
echo First run detected. Proceeding with setup...
echo.

:: Find a working Python with tkinter
call :find_python
if "%PYTHON_CMD%"=="" (
    echo ERROR: No Python installation with tkinter found.
    echo Please install Python 3.7+ from https://www.python.org/downloads/
    echo Ensure the "tcl/tk and IDLE" option is checked during installation.
    pause
    exit /b 1
)

echo Using Python: %PYTHON_CMD%
echo.

:: Create virtual environment
echo Creating virtual environment...
if exist venv rmdir /s /q venv
%PYTHON_CMD% -m venv venv
if %errorlevel% neq 0 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

:: Activate and upgrade pip
call venv\Scripts\activate.bat
echo Upgrading pip...
python -m pip install --upgrade pip

:: Install Python packages
echo Installing Python packages...
pip install customtkinter Pillow py7zr rarfile
if %errorlevel% neq 0 (
    echo Retrying with --no-cache-dir...
    pip install --no-cache-dir customtkinter Pillow py7zr rarfile
    if %errorlevel% neq 0 (
        echo ERROR: Failed to install required packages.
        pause
        exit /b 1
    )
)

:: --------------------------------------------------
:: Install 7-Zip silently
:: --------------------------------------------------
call :install_7zip

:: --------------------------------------------------
:: RAR support reminder
:: --------------------------------------------------
echo.
echo NOTE: RAR archive extraction requires UnRAR.exe.
echo You can install WinRAR from https://www.win-rar.com/
echo.

:: --------------------------------------------------
:: Launch GUI
:: --------------------------------------------------
:launch
if not exist "gui.py" (
    echo ERROR: gui.py not found in current directory.
    pause
    exit /b 1
)

echo ======================================
echo Launching Auto-Backpork GUI...
echo ======================================
python gui.py
if %errorlevel% neq 0 (
    echo.
    echo Application exited with error code %errorlevel%.
    pause
)
exit /b %errorlevel%

:: --------------------------------------------------
:: Function: find_python - locate Python with _tkinter
:: --------------------------------------------------
:find_python
set PYTHON_CMD=

:: Try 'py' launcher first
where py >nul 2>&1
if %errorlevel% equ 0 (
    py -c "import _tkinter" >nul 2>&1
    if !errorlevel! equ 0 (
        set PYTHON_CMD=py
        goto :eof
    )
)

:: Try 'python'
where python >nul 2>&1
if %errorlevel% equ 0 (
    python -c "import _tkinter" >nul 2>&1
    if !errorlevel! equ 0 (
        set PYTHON_CMD=python
        goto :eof
    )
)

:: Try 'python3'
where python3 >nul 2>&1
if %errorlevel% equ 0 (
    python3 -c "import _tkinter" >nul 2>&1
    if !errorlevel! equ 0 (
        set PYTHON_CMD=python3
        goto :eof
    )
)
goto :eof

:: --------------------------------------------------
:: Function: install_7zip - silent install
:: --------------------------------------------------
:install_7zip
echo Checking for 7-Zip...

:: Check if already installed (7z.exe in PATH)
where 7z >nul 2>&1
if %errorlevel% equ 0 (
    echo 7-Zip already installed.
    goto :eof
)

:: Check common install location
if exist "C:\Program Files\7-Zip\7z.exe" (
    echo 7-Zip found at default location.
    set "PATH=%PATH%;C:\Program Files\7-Zip"
    goto :eof
)

echo 7-Zip not found. Downloading and installing silently...

:: Determine architecture
set "ARCH=x64"
if "%PROCESSOR_ARCHITECTURE%"=="x86" if "%PROCESSOR_ARCHITEW6432%"=="" set "ARCH=x86"

:: Download latest 7-Zip installer (MSI for easier silent install)
set "URL=https://www.7-zip.org/a/7z2409-%ARCH%.msi"
set "INSTALLER=%TEMP%\7z-install.msi"

echo Downloading 7-Zip for %ARCH%...
powershell -Command "Invoke-WebRequest -Uri '%URL%' -OutFile '%INSTALLER%'" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Failed to download 7-Zip installer.
    echo Please install 7-Zip manually from https://www.7-zip.org/
    goto :eof
)

echo Installing 7-Zip silently...
msiexec /i "%INSTALLER%" /quiet /norestart
if %errorlevel% neq 0 (
    echo WARNING: MSI installation failed, trying EXE installer...
    set "URL=https://www.7-zip.org/a/7z2409-%ARCH%.exe"
    set "INSTALLER=%TEMP%\7z-install.exe"
    powershell -Command "Invoke-WebRequest -Uri '!URL!' -OutFile '!INSTALLER!'" >nul 2>&1
    "!INSTALLER!" /S
)

:: Clean up
del "%INSTALLER%" >nul 2>&1

:: Add to PATH for this session
set "PATH=%PATH%;C:\Program Files\7-Zip"
echo 7-Zip installation complete.
goto :eof
