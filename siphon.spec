# siphon.spec
#
# Build with:  pyinstaller siphon.spec --noconfirm      (or just run build.bat)
#
# Makes ONE folder, dist\siphon, with two programs sharing the same files:
#   siphon.exe      the window (no black console box behind it)
#   siphon-cli.exe  the same thing for the terminal (prints its output)
# A folder starts faster than a single-file exe, which unpacks itself on every launch.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ttkbootstrap keeps its themes as data files, lxml and Pillow load some modules by name,
# which PyInstaller can't spot on its own
datas = collect_data_files("ttkbootstrap")
# our icon: shipped as a data file (the window loads it) and stamped on both exes (what Explorer shows)
ICON = "siphon_app/assets/siphon.ico"
datas += [(ICON, "siphon_app/assets")]
hidden = collect_submodules("ttkbootstrap") + ["lxml.etree", "lxml._elementpath", "PIL._tkinter_finder"]

# things the app never uses, so they stay out of the build (don't add lxml here)
skip = ["pytest", "unittest", "pydoc", "test", "IPython", "matplotlib", "numpy"]


def analyse(script):
    return Analysis([script], pathex=["."], datas=datas, hiddenimports=hidden,
                    excludes=skip, noarchive=False)


gui = analyse("launch_gui.py")
cli = analyse("launch_cli.py")
MERGE((gui, "launch_gui", "siphon"), (cli, "launch_cli", "siphon-cli"))   # share files instead of copying them twice

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="siphon",
              console=False, upx=False, icon=ICON)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="siphon-cli",
              console=True, upx=False, icon=ICON)

COLLECT(gui_exe, gui.binaries, gui.datas,
        cli_exe, cli.binaries, cli.datas,
        upx=False, name="siphon")
