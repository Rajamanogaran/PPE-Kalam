#!/usr/bin/env python
"""
Convenience launcher — mirrors Streamlit's `streamlit run app.py`
Usage: python run.py  (runs Django dev server on 0.0.0.0:8000)
"""
import os
import sys
from pathlib import Path

def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ppe_project.settings')
    # Auto-migrate on first run
    try:
        import django
        from django.core.management import execute_from_command_line
        # Ensure DB exists
        execute_from_command_line([sys.argv[0], 'migrate', '--run-syncdb'])
    except Exception as e:
        print(f"⚠️ Auto-migrate failed: {e}")

    from django.core.management import execute_from_command_line
    # Default to runserver 0.0.0.0:8000 for preview compatibility
    args = sys.argv[1:] or ['runserver', '0.0.0.0:8000']
    # Ensure allowed hosts / CSRF handled
    execute_from_command_line([sys.argv[0]] + args)

if __name__ == '__main__':
    main()
