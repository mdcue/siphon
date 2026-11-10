@echo off
rem build.bat
rem
rem Makes the Windows programs. Run it from the project folder:  build.bat
rem You get dist\siphon\ (siphon.exe and siphon-cli.exe) and a zip you can upload as a release.

call .venv\Scripts\activate
if errorlevel 1 goto failed

python -m pip install --quiet pyinstaller
if errorlevel 1 goto failed

rem --clean throws away the last build's leftovers, so an old file can't sneak in
pyinstaller siphon.spec --noconfirm --clean
if errorlevel 1 goto failed

rem the version comes from siphon_app\__init__.py, so the zip name always matches
for /f %%v in ('python -c "import siphon_app; print(siphon_app.__version__)"') do set VERSION=%%v
if exist dist\siphon-%VERSION%-windows.zip del dist\siphon-%VERSION%-windows.zip
powershell -NoProfile -Command "Compress-Archive -Path dist\siphon -DestinationPath dist\siphon-%VERSION%-windows.zip"
if errorlevel 1 goto failed

echo.
echo Done: dist\siphon\siphon.exe and dist\siphon-%VERSION%-windows.zip
goto :eof

:failed
echo.
echo The build failed. Scroll up to see why.
exit /b 1
