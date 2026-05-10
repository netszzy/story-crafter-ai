@echo off
title AI 小说写作台
cd /d "D:\cc\novel"
echo 启动 AI 小说写作台...
echo 浏览器会自动打开，关闭此窗口即停止服务。
echo.
call ".venv\Scripts\activate.bat"
".venv\Scripts\streamlit.exe" run webui.py --server.headless false --browser.gatherUsageStats false
pause
