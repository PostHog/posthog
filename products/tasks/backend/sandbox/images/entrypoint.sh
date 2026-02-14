#!/bin/bash
set -e

if [ -f /app/requirements.txt ]; then
    pip install --no-cache-dir -r /app/requirements.txt
fi

exec streamlit run /app/app.py
