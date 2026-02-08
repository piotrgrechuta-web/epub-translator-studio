$ErrorActionPreference = "Stop"

Write-Host "== Preflight: py_compile =="
python -m py_compile app_main.py app_gui_classic.py app_gui_horizon.py start.py start_horizon.py tlumacz_ollama.py project_db.py epub_enhancer.py studio_suite.py app_events.py

Write-Host "== Preflight: pytest =="
python -m pytest -q

Write-Host "== Preflight PASS =="
