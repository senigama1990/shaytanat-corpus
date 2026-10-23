@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Сборка Shaytanat.exe. Нужен интернет: один раз устанавливается PyInstaller.
echo.
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto err
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Shaytanat --icon icon.ico --add-data "web;web" shaytanat_app.pyw
if errorlevel 1 goto err
echo.
echo Готово: dist\Shaytanat.exe
echo Этот файл можно отправить кому угодно: запуск двойным щелчком, Python не нужен.
explorer dist
pause
exit /b 0
:err
echo.
echo Сборка не удалась. Сделайте снимок экрана этого окна и пришлите его.
pause
