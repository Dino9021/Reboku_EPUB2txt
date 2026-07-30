@echo off
REM ---------------------------------------------------------------------------
REM  Build EPUB2txt.exe - one self-contained Windows executable.
REM
REM  The result needs NOTHING on the target machine: no Python, no Pillow, no
REM  Tcl/Tk. Copy dist\EPUB2txt.exe anywhere and run it.
REM
REM  Double-click this file, or run it from a terminal. Pure ASCII and no chcp
REM  on purpose - cmd mis-parses UTF-8 batch files.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set NAME=EPUB2txt
set SOURCE=EPUB2txt.py

echo.
echo === EPUB2txt - standalone .exe build ===
echo.

REM -- 1. find a Python ---------------------------------------------------------
set PY=
where py >nul 2>&1 && set PY=py -3
if not defined PY where python >nul 2>&1 && set PY=python
if not defined PY (
    echo ERROR: no Python found on PATH. Install Python 3.8 or newer first.
    goto :fail
)
%PY% --version
if errorlevel 1 (
    echo ERROR: "%PY%" would not run.
    goto :fail
)

REM -- 2. make sure the build tools and the one runtime dependency are present --
REM     Pillow is what turns the EPUB cover into the embedded JPEG. Without it
REM     the .exe still converts books, it just always writes "Cover: False".
echo.
echo --- checking build requirements ---
%PY% -m pip install --quiet --upgrade pyinstaller pillow
if errorlevel 1 (
    echo ERROR: could not install pyinstaller / pillow.
    echo        Check the network, or run: %PY% -m pip install pyinstaller pillow
    goto :fail
)

REM -- 2b. a running copy would hold dist\EPUB2txt.exe open ---------------------
REM     PyInstaller only reports "Access is denied" for this, which tells you nothing.
tasklist /FI "IMAGENAME eq %NAME%.exe" 2>nul | find /I "%NAME%.exe" >nul
if not errorlevel 1 (
    echo.
    echo ERROR: %NAME%.exe is still running - close it first.
    echo        The build cannot overwrite dist\%NAME%.exe while a copy is open.
    goto :fail
)

REM -- 3. the source has to pass its own checks before it gets frozen ----------
echo.
echo --- self-test ---
%PY% "%SOURCE%" --self-test
if errorlevel 1 (
    echo ERROR: the self-test failed - not building a broken .exe.
    goto :fail
)

REM -- 4. build ----------------------------------------------------------------
REM   --onefile  : a single .exe, nothing beside it to copy
REM   --windowed : NO console is ever created, so a double-click does not flash a
REM                black box while the one-file archive unpacks. The command line
REM                still works: _use_parent_console() in the source attaches to the
REM                terminal it was started from. Do NOT switch this back to
REM                --console - hiding the window from Python happens far too late.
REM   --icon     : OPTIONAL. icon.ico is a brand image and is not part of this
REM                repository, so the build simply leaves it out when the file is
REM                absent - you get the same program with PyInstaller's default icon.
REM   --collect-submodules PIL : the cover encoder is imported lazily, inside a
REM                function, so it is spelled out here rather than left to the
REM                dependency scan.
set ICON=
if exist "icon.ico" set ICON=--icon "icon.ico"
if not defined ICON echo     (no icon.ico - building with the default icon)
echo.
echo --- building (this takes a minute) ---
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "%NAME%" ^
    %ICON% ^
    --collect-submodules PIL ^
    --exclude-module numpy ^
    --exclude-module pytest ^
    "%SOURCE%"
if errorlevel 1 (
    echo ERROR: the build failed - see the messages above.
    goto :fail
)

REM -- 5. prove the .exe actually runs -----------------------------------------
REM   The .exe does NOT carry selftest.py (a development file, not part of a release), so asking
REM   for --self-test would print "not part of this distribution" and exit 0 - a gate that
REM   always passes is worse than none. The real question about a frozen build is whether it
REM   converts, so it is made to convert the sample and the output is compared, byte for byte,
REM   against the frozen samples\Sample.txt. That catches what freezing actually breaks:
REM   a missing lazy import, a dead resource path, a PyInstaller stub that cannot start.
REM
REM   start /wait: a windowed program does not hold the shell, so a plain call would return
REM   before the conversion finished and ERRORLEVEL would be meaningless.
echo.
echo --- verifying the built .exe ---
if exist "%TEMP%\epub2txt-verify" rmdir /s /q "%TEMP%\epub2txt-verify" 2>nul
mkdir "%TEMP%\epub2txt-verify" 2>nul
start "" /wait "dist\%NAME%.exe" "samples\Sample.epub" -o "%TEMP%\epub2txt-verify" -f
if errorlevel 1 (
    echo ERROR: the built .exe failed to run.
    goto :fail
)
if not exist "%TEMP%\epub2txt-verify\Sample.txt" (
    echo ERROR: the built .exe produced no output.
    goto :fail
)
%PY% -c "import sys,hashlib,pathlib; a=hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest(); b=hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest(); sys.exit(0 if a==b else 1)" "%TEMP%\epub2txt-verify\Sample.txt" "samples\Sample.txt"
if errorlevel 1 (
    echo ERROR: the built .exe does not reproduce samples\Sample.txt byte for byte.
    goto :fail
)
rmdir /s /q "%TEMP%\epub2txt-verify" 2>nul
echo     OK - reproduces samples\Sample.txt byte for byte.

REM -- 6. tidy up the intermediates, keep the .exe -----------------------------
rmdir /s /q build 2>nul
del "%NAME%.spec" 2>nul

echo.
echo === DONE ===
for %%F in ("dist\%NAME%.exe") do echo   %%~fF  (%%~zF bytes)
echo.
echo   Copy that one file to any Windows PC - nothing else is needed.
echo   Double-click it for the window, or from a terminal:
echo       %NAME%.exe C:\books -r -o C:\out
echo       %NAME%.exe --help
echo.
pause
exit /b 0

:fail
echo.
echo === BUILD FAILED ===
echo.
pause
exit /b 1
