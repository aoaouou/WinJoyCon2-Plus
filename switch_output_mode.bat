@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo.
echo  WinJoyCon2-Plus - switch output mode
echo.
echo  [1] hidmaestro : native Joy-Con 2 (VID 057E / PID 2067+2066)
echo  [2] joycon1    : virtual Joy-Con 1 (legacy, Ryujinx / Eden)
echo.
set /p CH=Select 1 or 2:
if "%CH%"=="1" goto HM
if "%CH%"=="2" goto J1
goto END
:HM
"C:\Users\nuonu\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -c "import configparser,sys; p='config.ini'; c=configparser.ConfigParser(); c.read(p,encoding='utf-8'); c.set('Controller','output_mode','hidmaestro'); c.write(open(p,'w',encoding='utf-8'))"
echo  Switched to hidmaestro. Restart the app.
goto END
:J1
"C:\Users\nuonu\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -c "import configparser,sys; p='config.ini'; c=configparser.ConfigParser(); c.read(p,encoding='utf-8'); c.set('Controller','output_mode','joycon1'); c.write(open(p,'w',encoding='utf-8'))"
echo  Switched to joycon1. Restart the app.
goto END
:END
echo.
pause
