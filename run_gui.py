"""Entry point for PyInstaller and direct invocation.

PyInstaller can't target a package module (`bwexport.gui`) directly — it needs a
runnable script. This launcher gives it one. Also handy for `python run_gui.py`
during development.
"""
from bwexport.gui import main

if __name__ == "__main__":
    main()
