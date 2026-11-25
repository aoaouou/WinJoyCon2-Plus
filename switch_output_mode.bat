@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo.
echo  WinJoyCon2-Plus - switch output mode
echo.
echo  [1] jc2     : native Joy-Con 2 (057E:2067/2066, HIDMaestro)
echo  [2] grip    : charging grip (057E:200E, full functions in SDL)
echo  [3] joycon1 : virtual Joy-Con 1 (legacy)
echo.
set /p CH=Select 1/2/3:
if "%CH%"=="1" goto JC2
if "%CH%"=="2" goto GRIP
if "%CH%"=="3" goto J1
goto END
:JC2
"C:\Users\nuonu\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -c "import configparser; p='config.ini'; c=configparser.ConfigParser(); c.read(p,encoding='utf-8'); c.set('Controller','output_mode','hidmaestro'); c.write(open(p,'w',encoding='utf-8'))"
echo  Switched to native JC2. Restart the app.
goto END
:GRIP
"C:\Users\nuonu\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -c "import configparser; p='config.ini'; c=configparser.ConfigParser(); c.read(p,encoding='utf-8'); c.set('Controller','output_mode','grip'); c.write(open(p,'w',encoding='utf-8'))"
echo  Switched to charging grip. Restart the app.
goto END
:J1
"C:\Users\nuonu\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -c "import configparser; p='config.ini'; c=configparser.ConfigParser(); c.read(p,encoding='utf-8'); c.set('Controller','output_mode','joycon1'); c.write(open(p,'w',encoding='utf-8'))"
echo  Switched to joycon1. Restart the app.
goto END
:END
echo.
pause
