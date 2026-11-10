"""
siphon_app/__main__.py

python -m siphon_app            opens the window
python -m siphon_app <address>  runs from the command line (see cli.py, or add --help)
"""
import sys

if len(sys.argv) > 1:
    from siphon_app.cli import main      # imported here so the command line never loads tkinter
else:
    from siphon_app.gui.app import main

main()
