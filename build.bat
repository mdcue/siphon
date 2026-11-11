@echo off
rem build.bat
rem
rem Makes the Windows programs. Run it from the project folder:  build.bat
rem You get dist\siphon\ (siphon.exe and siphon-cli.exe) and a zip you can upload as a release.

call .venv\Scripts\activate
if errorlevel 1 goto failed

python -m pip install --quiet pyinstaller
if errorlevel 1 goto failed

rem look for known security problems in the libraries. It only warns: you decide what to do
python -m pip install --quiet pip-audit
python -m pip_audit
if errorlevel 1 echo.& echo WARNING: pip-audit found known problems above. Update that library before you release.& echo.

rem --clean throws away the last build's leftovers, so an old file can't sneak in
pyinstaller siphon.spec --noconfirm --clean
if errorlevel 1 goto failed

rem the licences of everything bundled travel with the program
python make_notices.py dist\siphon\THIRD_PARTY_NOTICES.txt
if errorlevel 1 goto failed
copy /y LICENSE dist\siphon\LICENSE >nul
if errorlevel 1 goto failed

rem the version comes from siphon_app\__init__.py, so the zip name always matches
for /f %%v in ('python -c "import siphon_app; print(siphon_app.__version__)"') do set VERSION=%%v
if exist dist\siphon-%VERSION%-windows.zip del dist\siphon-%VERSION%-windows.zip
rem tar (built into Windows 10 and 11) makes the zip. PowerShell's Compress-Archive trips over files that
rem antivirus is still scanning, and it can fail without setting an error
tar -a -c -f dist\siphon-%VERSION%-windows.zip -C dist siphon
if errorlevel 1 goto failed

echo.
echo Done: dist\siphon\siphon.exe and dist\siphon-%VERSION%-windows.zip
echo Checksum for the release notes:
certutil -hashfile dist\siphon-%VERSION%-windows.zip SHA256
goto :eof

:failed
echo.
echo The build failed. Scroll up to see why.
exit /b 1
