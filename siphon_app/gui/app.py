"""
siphon_app/gui/app.py

The main window: a URL bar, a place for the tables, and a status bar.
Downloading and parsing run on a background thread so the window never freezes.
The table list, the cleaning switch and exporting live in their own files.
"""
import queue
import threading
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog
from urllib.parse import urlparse

import ttkbootstrap as ttk

# [CHANGED] now also imports the real download and the parser
from siphon_app.core.fetcher import FetchCancelled, FetchError, normalize_url # fetch is no longer imported from here
from siphon_app.core.localfile import read_html_file
from siphon_app.core.models import Table
from siphon_app.core.parser import parse_page
from siphon_app.core.polite import forget, polite_fetch as fetch #the polite downloader, still called fetch here
from siphon_app.core.pipeline import clean_all, summarize
from siphon_app.gui.export_bar import ExportBar, default_folder # also default_folder
from siphon_app.gui.table_view import TableView
from siphon_app.settings import (
    MIN_HEIGHT, MIN_WIDTH, Settings, load_settings, remember_url, save_settings, settings_path,
)

LIGHT_THEME = "bootstrap-light"  # ttkbootstrap 2.x ships matching -light / -dark pairs
DARK_THEME = "bootstrap-dark"  # needed now, because the app can start in dark mode
PAD = 12 # space around things, in pixels
POLL_MS = 50 # how often the window checks the worker for news

READY_TEXT = "Paste a link to a page with tables, then press Fetch."

# This runs on the worker thread. It must NEVER touch the window or any widget:
# tkinter is not thread-safe. Its only way to talk back is the results queue.
def run_job(results: queue.Queue, job_id: int, url: str, cancel_event: threading.Event, loader=None) -> None:
    # loader is a function that gets the page some other way (reading a file from disk)
    try:
        page = loader() if loader else fetch(url, cancel_event=cancel_event)
        if cancel_event.is_set(): # cancelled while the page was arriving
            raise FetchCancelled("Cancelled.")
        tables = parse_page(page)
        cleaned = clean_all(tables)  # slow on big tables, so it happens here
        message = ("done", job_id, tables, cleaned, page.note) # also carries a note for the status bar
    except FetchCancelled:
        message = ("cancelled", job_id)
    except FetchError as error: # friendly, already worded for the user
        message = ("error", job_id, str(error))
    except Exception as error: # a bug: still tell the user, never hang
        message = ("error", job_id,
                f"Something went wrong while reading that page ({type(error).__name__}).")
    results.put(message)


class SiphonApp(ttk.Window):
    def __init__(self, settings_path_override: Path | None = None) -> None:
        #load what we remembered BEFORE the window exists, so it opens the way you left it.
        # Tests pass their own path, so they never touch your real settings.
        path = Path(settings_path_override) if settings_path_override else settings_path()
        saved = load_settings(path)
        super().__init__(title="siphon.", themename=DARK_THEME if saved.theme == "dark" else LIGHT_THEME,
                        size=(saved.window_width, saved.window_height), minsize=(MIN_WIDTH, MIN_HEIGHT))
        self.settings_file = path
        self.settings: Settings = saved
        self.geometry(f"{min(saved.window_width, self.winfo_screenwidth())}x"
                    f"{min(saved.window_height, self.winfo_screenheight())}") # never bigger than the screen

        self.url_var = ttk.StringVar()
        self.status_var = ttk.StringVar(value=READY_TEXT)
        self.status_is_error = False

        #everything the background work needs
        self.tables: list[Table] = []  # what the last successful fetch found, as on the page
        self.cleaned_tables: list[Table] = []  # the same tables with numbers converted
        self.clean_summary = ""  # one sentence about what cleaning did
        self.busy = False  # True while a download is running
        self._results: queue.Queue = queue.Queue() # worker -> window messages
        self._cancel_event: threading.Event | None = None
        self._job_id = 0 # lets us ignore answers from cancelled jobs
        self._poll_id = None # the pending "check for news" timer
        self._job_url: str | None = None # address to remember if this job succeeds

        self.columnconfigure(0, weight=1) # the middle row stretches with the window
        self.rowconfigure(1, weight=1)
        self._build_top_bar()
        self._build_content()
        self._build_status_bar()
        self._apply_settings() # put the remembered choices into the controls

        self.bind("<Control-l>", lambda event: self._focus_url()) # like a browser's address bar
        self.bind("<Control-o>", lambda event: self.on_open_file()) # like every other program
        self.bind("<Control-r>", lambda event: self.on_fetch(fresh=True))  # reload: download again
        self.bind("<Escape>", lambda event: self.on_cancel()) #Esc cancels a download
        self.protocol("WM_DELETE_WINDOW", self.on_close)# stop work when closing
        self.after(100, self._focus_url)

    # layout
    def _build_top_bar(self) -> None:
        bar = ttk.Frame(self, padding=PAD)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1) # the URL box takes all the spare width

        ttk.Label(bar, text="URL").grid(row=0, column=0, padx=(0, 8))
        #was a plain Entry; a Combobox is an Entry with a drop-down list of recent addresses
        self.url_entry = ttk.Combobox(bar, textvariable=self.url_var, values=self.settings.recent_urls)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        self.url_entry.bind("<Return>", lambda event: self.on_fetch())
        self.url_entry.bind("<<ComboboxSelected>>", lambda event: self.on_fetch())# picking one fetches it

        self.fetch_button = ttk.Button(bar, text="Fetch", bootstyle="primary", command=self.on_fetch)
        self.fetch_button.grid(row=0, column=2, padx=(8, 0))

        # opens a page you saved from your browser
        self.open_button = ttk.Button(bar, text="Open file...", bootstyle="secondary-outline",
                                    command=self.on_open_file)
        self.open_button.grid(row=0, column=3, padx=(8, 0))

        self.cancel_button = ttk.Button(bar, text="Cancel", bootstyle="danger-outline",
                                        command=self.on_cancel, state="disabled")
        self.cancel_button.grid(row=0, column=4, padx=(8, 0))

        self.theme_button = ttk.Button(bar, text="Dark", width=6, bootstyle="secondary-outline",
                                    command=self.toggle_theme)
        self.theme_button.grid(row=0, column=5, padx=(8, 0))

    def _build_content(self) -> None:
        #the placeholder label is gone: the table list and preview live here now
        self.content = ttk.Frame(self, padding=PAD)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self.table_view = TableView(self.content, notify=self.set_status)
        self.table_view.grid(row=0, column=0, sticky="nsew")
        #the export strip sits under the preview and exports whatever is ticked
        self.export_bar = ExportBar(self.content, get_tables=self.table_view.checked_tables,
                                    notify=self.set_status, on_clean_change=self._on_clean_change,
                                    on_saved=self.save_settings) #remember after each save
        self.export_bar.grid(row=1, column=0, sticky="ew", pady=(PAD, 0))
        self.table_view.on_change = self.export_bar.refresh # ticking a box updates the button

    def _build_status_bar(self) -> None:
        ttk.Separator(self).grid(row=2, column=0, sticky="ew")
        #the status text and a small progress bar now share one row
        bar = ttk.Frame(self)
        bar.grid(row=3, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(bar, textvariable=self.status_var, padding=(PAD, 8), anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=1, padx=(0, PAD))
        self.progress.grid_remove() # hidden until a download starts

    #actions
    def _focus_url(self) -> None:
        self.url_entry.focus_set()
        self.url_entry.selection_range(0, "end")

    def set_status(self, text: str, *, error: bool = False) -> None:
        """Show a message at the bottom. Errors are red so they are hard to miss."""
        self.status_var.set(text)
        self.status_is_error = error
        self.status_label.configure(bootstyle="danger" if error else "default")

    def toggle_theme(self) -> None:
        mode = self.style.toggle_theme()# switches bootstrap-light <-> bootstrap-dark
        self.theme_button.configure(text="Light" if mode == "dark" else "Dark") # offer the other one

    #remembering things
    def _apply_settings(self) -> None:
        """Put the remembered choices into the controls (the window itself was set up in __init__)."""
        saved = self.settings
        bar = self.export_bar
        folder = saved.export_folder
        bar.folder_var.set(folder if folder and Path(folder).is_dir() else default_folder()) # a vanished folder falls back
        bar.format_var.set(saved.export_format)
        bar.clean_var.set(saved.clean_numbers)
        bar.refresh() # the hint under "Save as" follows the format
        bar.set_clean_text()
        self.theme_button.configure(text="Light" if saved.theme == "dark" else "Dark")

    def collect_settings(self) -> Settings:
        """Read the controls back into a Settings (a copy; nothing is saved yet)."""
        bar = self.export_bar
        current = replace(self.settings, recent_urls=list(self.settings.recent_urls))
        current.theme = "dark" if self.style.theme_mode == "dark" else "light"
        current.export_folder = bar.folder_var.get().strip()
        current.export_format = bar.format_var.get()
        current.clean_numbers = bar.clean_var.get()
        width, height = self.winfo_width(), self.winfo_height()
        if self.state() == "normal" and width >= MIN_WIDTH and height >= MIN_HEIGHT:
            current.window_width, current.window_height = width, height  # a maximised or hidden window keeps the old size
        return current

    def save_settings(self) -> None:
        """Remember how things are now. A failure to write is ignored: it is only a convenience."""
        self.settings = self.collect_settings()
        save_settings(self.settings, self.settings_file)

    # was a stub that only checked the address; now it starts the real download
    def on_fetch(self, fresh: bool = False) -> None:
        if self.busy: # Enter pressed twice must not start two downloads
            return
        try:
            url = normalize_url(self.url_var.get())
        except FetchError as error:
            self.set_status(str(error), error=True)
            return
        self.url_var.set(url) # show the tidied address back to the user
        if fresh: #Ctrl+R: skip the remembered copy
            forget(url)
        self._start_job(url)

    #background work
    def on_open_file(self) -> None:
        """[NEW] Read a web page you saved from your browser instead of downloading one."""
        if self.busy:
            return
        chosen = filedialog.askopenfilename(
            parent=self, title="Open a saved web page", initialdir=default_folder(),
            filetypes=[("Web pages", "*.html *.htm *.xhtml"), ("All files", "*.*")])
        if not chosen: # empty if the person pressed Cancel
            return
        self._start_job(Path(chosen).as_uri(), loader=lambda: read_html_file(chosen),
                        status=f"Reading {Path(chosen).name} ...", remember=False)

    def _start_job(self, url: str, *, loader=None, status: str | None = None, remember: bool = True) -> None:
        #can also run a "loader" (reading a file) through the very same background job
        self._job_id += 1
        self._cancel_event = threading.Event()
        self._job_url = url if remember else None # only downloaded addresses go in the recent list
        self._set_busy(True)
        self.set_status(status or f"Downloading from {urlparse(url).hostname} ...")
        threading.Thread(target=run_job, args=(self._results, self._job_id, url, self._cancel_event),
                        kwargs={"loader": loader}, daemon=True).start()   # daemon: it can't keep the program alive
        self._schedule_poll()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.fetch_button.configure(state="disabled" if busy else "normal")
        self.open_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.grid()
            self.progress.start(15)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def _schedule_poll(self) -> None:
        if self._poll_id is not None: # never run two pollers at once
            self.after_cancel(self._poll_id)
        self._poll_id = self.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        """Runs on the window's own thread: pick up anything the worker has reported."""
        self._poll_id = None
        try:
            while True:
                self._handle(self._results.get_nowait())
        except queue.Empty:
            pass
        if self.busy:
            self._schedule_poll()

    def _handle(self, message: tuple) -> None:
        kind, job_id = message[0], message[1]
        if job_id != self._job_id: # an answer from a job we already cancelled
            return
        self._set_busy(False)
        if kind == "done":
            self._show_tables(message[2], message[3]) # also gets the cleaned copies
            note = message[4] if len(message) > 4 else ""# e.g. "Used the copy from 40 seconds ago..."
            if note:
                self.set_status(f"{self.status_var.get()} {note}")
            self._remember_job_url()
        elif kind == "error":
            self.set_status(message[2], error=True)
        else: # "cancelled"
            self.set_status("Cancelled.")

    def on_cancel(self) -> None:
        if not self.busy:
            return
        self._cancel_event.set() # ask the worker to stop as soon as it can
        self._job_id += 1 # whatever it sends back from now on is ignored
        self._set_busy(False)  # and the window is free again straight away
        self.set_status("Cancelled.")

    def _on_clean_change(self, clean: bool) -> None:
        """[NEW] The "Clean numbers" box was ticked or unticked: flip the preview and the export."""
        if self.tables:
            self.table_view.swap_tables(self.cleaned_tables if clean else self.tables)
        self.export_bar.set_clean_text(self.clean_summary if clean and self.tables else None)

    def _show_tables(self, tables: list[Table], cleaned: list) -> None:
        # this takes the cleaned copies too, and shows whichever version the box asks for
        self.tables = tables
        self.cleaned_tables = [table for table, report in cleaned]
        self.clean_summary = summarize([report for table, report in cleaned])
        if not tables:
            self.table_view.set_tables([], "No tables found on that page.")
            self.export_bar.set_clean_text()
            self.set_status("No tables found on that page. It may load its data with JavaScript.")
            return
        clean = self.export_bar.clean_var.get()
        self.table_view.set_tables(self.cleaned_tables if clean else tables)
        self.export_bar.set_clean_text(self.clean_summary if clean else None)
        word = "table" if len(tables) == 1 else "tables"
        text = f"Found {len(tables)} {word}"
        layout = sum(1 for table in tables if table.is_layout)
        if layout:
            text += f" ({layout} look{'s' if layout == 1 else ''} like page layout)"
        self.set_status(text + ".")

    def _remember_job_url(self) -> None:
        """[NEW] A page downloaded fine: add its address to the recent list and save."""
        if self._job_url:
            remember_url(self.settings, self._job_url)
            self.url_entry.configure(values=self.settings.recent_urls)
            self.save_settings()

    def on_close(self) -> None:
        self.save_settings() # remember the theme, the window size and the choices
        if self._cancel_event is not None:
            self._cancel_event.set() # tells a running download to give up
        self.destroy()


def main() -> None:
    SiphonApp().mainloop()


if __name__ == "__main__":
    main()