#!/bin/bash

# Change to the folder where this script lives
cd "$(dirname "$0")"

echo "============================================"
echo "   WhatsApp Bulk Sender — Starting up..."
echo "============================================"
echo ""

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo ""
    echo "Please install it from: https://www.python.org/downloads/"
    echo "Then double-click this file again."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

echo "Python found: $(python3 --version)"
echo ""

# Install / upgrade dependencies silently
echo "Installing dependencies (first run may take a minute)..."
python3 -m pip install -q --upgrade pip
python3 -m pip install -q streamlit pandas selenium webdriver-manager

echo "Dependencies ready."
echo ""

# Launch the app and open browser
echo "Launching app at http://localhost:8501 ..."
echo "(Close this window to stop the app)"
echo ""

open "http://localhost:8501" &
sleep 2
python3 -m streamlit run app.py --server.port 8501 --server.headless false
