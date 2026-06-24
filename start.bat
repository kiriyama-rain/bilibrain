@echo off
chcp 65001 >nul
title BiliBrain 服务端

cd /d "%~dp0"

echo.
echo   ========================================
echo     BiliBrain 服务端
echo   ========================================
echo.
echo   正在启动 Flask 后端 (端口 5577)...
echo.

python app.py

pause
