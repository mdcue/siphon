"""
siphon_app/gui/export_bar.py

The strip under the table preview: pick a format, tick "Clean numbers", choose a folder and
press Export. Saving runs on a background thread, so a big Excel file never freezes the window.
"""
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog

import ttkbootstrap as ttk

from siphon_app.core.exporter import ExportError
from siphon_app.core.models import Table
from siphon_app.core.pipeline import FORMAT_HINTS, FORMATS, describe, export_tables

POLL_MS = 50
CLEAN_ON_TEXT = "Numbers like $1,234 or 12% are saved as real numbers."
CLEAN_OFF_TEXT = "Showing and saving the text exactly as it is on the page."

#helpers
def default_folder() -> str:
    """The Downloads folder if there is one, otherwise the home folder."""
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.is_dir() else Path.home())

def export_label(count: int) -> str:
    if count == 0:
        return "Export"
    return f"Export {count} {'table' if count == 1 else 'tables'}"

def open_folder(folder: str | Path) -> None:
    """Show a folder in Explorer (or Finder / the file manager on other systems)."""
    if sys.platform == "win32":
        os.startfile(folder)                              # noqa: S606  (Windows only)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])

# This runs on a worker thread. Like run_job in app.py it must NEVER touch a widget:
# its only way to talk back is the queue.
def run_export(results: queue.Queue, tables: list[Table], fmt: str, folder: str) -> None:
    try:
        results.put(("saved", export_tables(tables, fmt, folder)))
    except ExportError as error:                          # already worded for the user
        results.put(("error", str(error)))
    except Exception as error:                            # a bug: still tell the user, never hang
        results.put(("error", f"Something went wrong while saving ({type(error).__name__})."))

#the widget
class ExportBar(ttk.Frame):
    def __init__(self, master, get_tables: Callable[[], list[Table]],
                notify: Callable[..., None] | None = None,
                on_clean_change: Callable[[bool], None] | None = None,
                on_saved: Callable[[], None] | None = None) -> None:
        super().__init__(master)
        self.get_tables = get_tables # what to export: the ticked tables
        self.notify = notify or (lambda text, error=False: None)
        self.on_clean_change = on_clean_change or (lambda clean: None)
        self.on_saved = on_saved or (lambda: None) # called after a successful save

        self.format_var = ttk.StringVar(value="csv")
        self.clean_var = ttk.BooleanVar(value=True)
        self.folder_var = ttk.StringVar(value=default_folder())
        self.busy = False
        self.last_folder: Path | None = None # set after a successful export
        self._results: queue.Queue = queue.Queue()
        self._poll_id = None

        self.columnconfigure(1, weight=1)
        self._build()
        self.refresh()

    def _build(self) -> None:
        ttk.Separator(self).grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))

        # -- row 1: format and cleaning
        ttk.Label(self, text="Save as").grid(row=1, column=0, sticky="w", padx=(0, 8))
        formats = ttk.Frame(self)
        formats.grid(row=1, column=1, sticky="w")
        for key, label in FORMATS.items():
            ttk.Radiobutton(formats, text=label, value=key, variable=self.format_var,
                            command=self._on_format).pack(side="left", padx=(0, 12))
        self.format_hint = ttk.Label(formats, text="", bootstyle="secondary")
        self.format_hint.pack(side="left")

        clean = ttk.Frame(self)
        clean.grid(row=2, column=1, columnspan=3, sticky="w", pady=(6, 0))
        self.clean_check = ttk.Checkbutton(clean, text="Clean numbers", variable=self.clean_var,
                                        command=self._on_clean)
        self.clean_check.pack(side="left")
        self.clean_label = ttk.Label(clean, text=CLEAN_ON_TEXT, bootstyle="secondary")
        self.clean_label.pack(side="left", padx=(12, 0))

        #row 3: folder and buttons
        ttk.Label(self, text="Folder").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.folder_entry = ttk.Entry(self, textvariable=self.folder_var)
        self.folder_entry.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        self.browse_button = ttk.Button(self, text="Browse...", bootstyle="secondary-outline",
                                        command=self.browse)
        self.browse_button.grid(row=3, column=2, padx=(8, 0), pady=(8, 0))
        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=3, padx=(8, 0), pady=(8, 0))
        self.export_button = ttk.Button(buttons, text="Export", bootstyle="success", command=self.on_export)
        self.export_button.pack(side="left")
        self.open_button = ttk.Button(buttons, text="Open folder", bootstyle="secondary-outline",
                                    command=self.on_open, state="disabled")
        self.open_button.pack(side="left", padx=(8, 0))

#keeping the controls in step
    def refresh(self) -> None:
        """Call whenever the ticked tables change: updates the Export button's text and state."""
        count = len(self.get_tables())
        self.export_button.configure(text=export_label(count),
                                    state="normal" if count and not self.busy else "disabled")
        self.format_hint.configure(text=FORMAT_HINTS[self.format_var.get()])

    def set_clean_text(self, text: str | None = None) -> None:
        """Say what cleaning did (or didn't). With no text, show the standard line for the checkbox."""
        if text is None:
            text = CLEAN_ON_TEXT if self.clean_var.get() else CLEAN_OFF_TEXT
        self.clean_label.configure(text=text)

    def _on_format(self) -> None:
        self.refresh()

    def _on_clean(self) -> None:
        self.on_clean_change(self.clean_var.get())

#actions
    def browse(self) -> None:
        chosen = filedialog.askdirectory(parent=self, initialdir=self.folder_var.get() or None,
                                        title="Choose where to save")
        if chosen:                                        # empty if the person pressed Cancel
            self.folder_var.set(os.path.normpath(chosen))

    def on_export(self) -> None:
        if self.busy:
            return
        tables = self.get_tables()
        if not tables:
            self.notify("Tick at least one table to export.", error=True)
            return
        self.busy = True
        self.refresh()
        self.notify("Saving ...")
        threading.Thread(target=run_export, args=(self._results, tables, self.format_var.get(),
                                                self.folder_var.get()), daemon=True).start()
        self._schedule_poll()

    def on_open(self) -> None:
        if self.last_folder is None:
            return
        try:
            open_folder(self.last_folder)
        except OSError:
            self.notify(f"Couldn't open {self.last_folder}.", error=True)

#hearing back from the worker
    def _schedule_poll(self) -> None:
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
        self._poll_id = self.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        try:
            kind, payload = self._results.get_nowait()
        except queue.Empty:
            self._schedule_poll() # not finished yet: look again shortly
            return
        self.busy = False
        if kind == "saved":
            self.last_folder = payload[0].parent
            self.open_button.configure(state="normal")
            self.notify(describe(payload))
            self.on_saved() # lets the window remember the folder and format
        else:
            self.notify(payload, error=True)
        self.refresh()