@echo off
title AnimeciX Downloader - Tek Tikla Calistir
color 0B

echo ==========================================
echo       AnimeciX Downloader Baslatiliyor
echo ==========================================
echo.
echo [1/3] Gereksinimler kontrol ediliyor...
pip install -r requirements.txt >nul 2>&1

echo [2/3] Tarayici motoru (Playwright) kontrol ediliyor...
playwright install chromium >nul 2>&1

echo [3/3] Hazir!
echo.
echo ==========================================
set /p link="Indirmek istediginiz AnimeciX linkini yapistirin (Saga tiklayarak yapistirabilirsiniz): "
echo ==========================================
echo.

python animecix_dl.py "%link%"

echo.
echo Islem tamamlandi. Cikmak icin bir tusa basin...
pause >nul
