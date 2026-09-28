@echo off
title Power BI Auditor Agent Service
echo ============================================================
echo   Power BI Auditor Agent - Servicio Eterno
echo ============================================================
echo Iniciando servidor FastAPI en http://localhost:8000 ...
echo Presione Ctrl+C para detener el servicio.
echo.

.\venv\Scripts\python.exe main.py
pause
