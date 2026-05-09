@echo off
setlocal

set "PROJECT_DIR=D:\cc\novel"
set "WEBUI_PORT=8501"
set "WEBUI_URL=http://localhost:%WEBUI_PORT%"
set "LOG_DIR=%PROJECT_DIR%\logs"
set "OUT_LOG=%LOG_DIR%\streamlit_%WEBUI_PORT%.out.log"
set "ERR_LOG=%LOG_DIR%\streamlit_%WEBUI_PORT%.err.log"
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"

cd /d "%PROJECT_DIR%" || (
    echo Failed to enter project directory: %PROJECT_DIR%
    pause
    exit /b 1
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
    >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)
if not exist "%USERPROFILE%\.streamlit\config.toml" (
    > "%USERPROFILE%\.streamlit\config.toml" echo [browser]
    >> "%USERPROFILE%\.streamlit\config.toml" echo gatherUsageStats = false
)

set "PYTHON_CMD=python"
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%PROJECT_DIR%\.venv\Scripts\python.exe"
)

where ollama >nul 2>nul
if %ERRORLEVEL%==0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
    if errorlevel 1 (
        echo Starting Ollama...
        start "Novel Ollama" /min cmd /k "ollama serve"
        timeout /t 3 /nobreak >nul
    ) else (
        echo Ollama is already running.
    )
) else (
    echo Ollama was not found in PATH. Skipping local model service.
)

"%PYTHON_CMD%" -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo Streamlit is not installed for: %PYTHON_CMD%
    echo Run setup first, or install dependencies in the project virtual environment.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', %WEBUI_PORT%); $client.Close(); exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo Starting Streamlit WebUI on %WEBUI_URL% ...
    start "Novel WebUI" /D "%PROJECT_DIR%" cmd /k ""%PYTHON_CMD%" -m streamlit run webui.py --server.port %WEBUI_PORT% --server.address 127.0.0.1 --server.headless false --browser.gatherUsageStats false 1>>"%OUT_LOG%" 2>>"%ERR_LOG%""
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(30); do { try { $client=New-Object Net.Sockets.TcpClient; $client.Connect('127.0.0.1', %WEBUI_PORT%); $client.Close(); exit 0 } catch { Start-Sleep -Milliseconds 500 } } while ((Get-Date) -lt $deadline); exit 1"
    if errorlevel 1 (
        echo Streamlit did not open port %WEBUI_PORT% within 30 seconds.
        echo Please check:
        echo   %OUT_LOG%
        echo   %ERR_LOG%
        pause
        exit /b 1
    )
) else (
    echo Streamlit WebUI is already running on %WEBUI_URL%.
)

start "" "%WEBUI_URL%"
exit /b 0
