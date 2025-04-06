@echo off
title Telegram Ghibli Bot (Async)
color 0A

echo ===================================================
echo         TELEGRAM GHIBLI BOT (ASYNC VERSION)
echo ===================================================
echo.

echo Остановка всех предыдущих экземпляров Python...
taskkill /F /IM python.exe /T 2>NUL
taskkill /F /IM pythonw.exe /T 2>NUL
echo --------------------------------------
echo Запуск асинхронного бота...
cd "C:\Users\Admin\Desktop\telegram-ghibli-bot"
python bot.py
pause
