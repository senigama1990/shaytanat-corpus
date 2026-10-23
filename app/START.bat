@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw "%~dp0shaytanat_app.pyw" & exit /b 0)
start "" python "%~dp0shaytanat_app.pyw"
