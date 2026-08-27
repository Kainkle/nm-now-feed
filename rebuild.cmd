@echo off
rem NM Now feed rebuild + push — run by the "nmnow-feed-rebuild" scheduled task every 30 min.
rem Keeps Titan (4h) and Phoenix (3h) stream tokens young; a failed build exits non-zero
rem and leaves the previous published feed in place (build.py failure policy).
cd /d C:\Dev\NMLauncher\Temp\nmnf
set PYTHONIOENCODING=utf-8
echo === %DATE% %TIME% === >> rebuild.log
python -m nmnowfeed.build --out feed --epg-dir C:\Users\Mayor\AppData\Local\Temp\epgcache >> rebuild.log 2>&1
if errorlevel 1 exit /b 1
git add -A feed >> rebuild.log 2>&1
git diff --cached --quiet >> rebuild.log 2>&1
if errorlevel 1 (
    git commit -m "auto rebuild" >> rebuild.log 2>&1
    git push -q origin main >> rebuild.log 2>&1
)
