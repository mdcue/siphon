"""
launch_cli.py

What PyInstaller starts for siphon-cli.exe (the terminal version).
Same as: python -m siphon_app <address>
"""
from siphon_app.cli import main

main()
