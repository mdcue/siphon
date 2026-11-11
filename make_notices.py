"""
make_notices.py

Writes THIRD_PARTY_NOTICES.txt: the licence of every library siphon ships with.
Almost all of them ask for one thing, that their licence text travels with the program,
so build.bat runs this and puts the result in the folder next to siphon.exe.

python make_notices.py dist\\siphon\\THIRD_PARTY_NOTICES.txt

It reads the licences from the packages installed in your .venv, so the list always matches
what was really bundled. Run it with the same environment you build in.
"""
import re
import sys
from importlib import metadata
from pathlib import Path

# what siphon imports directly; everything those need is found automatically
DIRECT = ["requests", "beautifulsoup4", "lxml", "openpyxl", "platformdirs", "ttkbootstrap"]

# files inside a package's metadata folder that hold licence text
LICENSE_FILE = re.compile(r"(^|/)(licen[sc]es?|copying|notice)([._-][^/]*)?$", re.IGNORECASE)

# things that are bundled but are not pip packages
EXTRA = """\
Python (PSF License 2.0)
    The Python runtime that runs siphon is bundled in the program.
    https://docs.python.org/3/license.html

Tcl/Tk (BSD-style licence)
    The windowing toolkit behind tkinter is bundled with Python.
    https://www.tcl-lang.org/software/tcltk/license.html

PyInstaller (GPL-2.0-or-later with a special exception)
    PyInstaller built the programs and its small start-up stub is inside them. Its licence
    has an explicit exception that lets programs built with it be distributed under any
    licence, so siphon itself stays MIT. https://pyinstaller.org/en/stable/license.html

Microsoft Visual C++ runtime (vcruntime140.dll and friends)
    Windows copies of Python need these. Microsoft allows them to be redistributed with
    programs. https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files

About lxml: its Windows build includes zlib (zlib licence), libxml2 and libxslt (MIT) and
libiconv (LGPL-2.1). The LGPL asks that you can replace that library: lxml sits as separate
files in the _internal folder of this program, so it can be swapped for another build.

About certifi: its licence (MPL-2.0) applies to the file of trusted website certificates
(cacert.pem). siphon ships it unchanged. Source: https://github.com/certifi/python-certifi
"""


def requirement_name(text: str) -> str | None:
    """'idna (>=2.5); extra == "socks"' -> 'idna'. None for optional extras."""
    if re.search(r"extra\s*==", text):
        return None
    return re.split(r"[\s;<>=!~\[(]", text.strip(), maxsplit=1)[0] or None


def collect(names: list[str]) -> list[metadata.Distribution]:
    """The listed packages plus everything they depend on, in name order."""
    found: dict[str, metadata.Distribution] = {}
    waiting = list(names)
    while waiting:
        name = waiting.pop()
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue                                  # not installed here (a Windows-only extra, say)
        key = dist.metadata["Name"].lower().replace("_", "-")
        if key in found:
            continue
        found[key] = dist
        for requirement in dist.requires or []:
            if (child := requirement_name(requirement)):
                waiting.append(child)
    return [found[key] for key in sorted(found)]


def license_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """(file name, text) for each licence file the package carries."""
    texts = []
    for file in dist.files or []:
        if LICENSE_FILE.search(file.as_posix()):
            try:
                texts.append((file.name, dist.locate_file(file).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                pass
    return texts


def licence_name(dist: metadata.Distribution) -> str:
    info = dist.metadata
    name = info.get("License-Expression") or info.get("License") or ""
    if not name or len(name) > 80:                    # some packages paste the whole licence in this field
        classifiers = [c.split("::")[-1].strip() for c in info.get_all("Classifier") or [] if c.startswith("License ::")]
        name = ", ".join(classifiers) or "see the licence text below"
    return name.splitlines()[0]


def build_notice(dists: list[metadata.Distribution]) -> str:
    bar = "=" * 78
    out = ["THIRD-PARTY NOTICES",
           "",
           "siphon is released under the MIT licence (see LICENSE). It includes the free software",
           "listed below, each under its own licence. Their licence texts follow.",
           "",
           "Libraries (installed with pip)"]
    for dist in dists:
        out.append(f"  - {dist.metadata['Name']} {dist.version}: {licence_name(dist)}")
    out += ["", "Also bundled", "", EXTRA]
    for dist in dists:
        texts = license_texts(dist)
        out += [bar, f"{dist.metadata['Name']} {dist.version}  ({licence_name(dist)})", bar, ""]
        if not texts:
            out += ["(this package ships no separate licence file; see its project page)", ""]
        for file_name, text in texts:
            out += [f"--- {file_name} ---", text.strip(), ""]
    return "\n".join(out) + "\n"


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "THIRD_PARTY_NOTICES.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    notice = build_notice(collect(DIRECT))
    target.write_text(notice, encoding="utf-8")
    print(f"Wrote {target} ({len(notice):,} characters)")


if __name__ == "__main__":
    main()
