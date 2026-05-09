@echo off
cd /d D:\cc\novel
streamlit run webui.py --server.port 8501 --server.headless false
pause
