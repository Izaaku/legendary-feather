"""
Legendary Feather - Local Development Entry Point
Run this file to start the app: python run.py
"""
import sys
import os

# Ensure the backend folder is in Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app, socketio
from app.utils.database import init_db
from app.utils.seed_admin import seed_admin

if __name__ == '__main__':
    init_db()
    seed_admin()
    print()
    print("  ✦ Legendary Feather Universal Translator")
    print("  ✦ Running on http://localhost:5000")
    print("  ✦ Press Ctrl+C to stop")
    print()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
