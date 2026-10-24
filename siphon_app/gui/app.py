"""
siphon_app/gui/app.py

The main window: a URL bar, a place for the tables, and a status bar.
Downloading and parsing run on a background thread so the window never freezes.
The table list, cleaning and exporting are added in later steps.
"""
import queue
import threading
from urllib.parse import urlparse

import ttkbootstrap as ttk

from siphon_app.core.fetcher import FetchCancelled, FetchError, fetch, normalize_url
from siphon_app.core.models import Table
from siphon_app.core.parser import parse_page
from siphon_app.gui.table_view import TableView

LIGHT_THEME = "bootstrap-light"  # ttkbootstrap 2.x ships matching -light / -dark pairs
PAD = 12 # space around things, in pixels
POLL_MS = 50

READY_TEXT = "Paste a link to a page with tables, then press Fetch."

def run_job(results: queue.Queue, job_id: int, url: str, cancel_event: threading.Event) -> None:
    try:
        page = fetch(url, cancel_event=cancel_event)
        if cancel_event.is_set(): # cancelled while the page was arriving
            raise FetchCancelled("Cancelled.")
        tables = parse_page(page)
        message = ("done", job_id, tables)
    except FetchCancelled:
        message = ("cancelled", job_id)
    except FetchError as error: # friendly, already worded for the user
        message = ("error", job_id, str(error))
    except Exception as error: # a bug: still tell the user, never hang
        message = ("error", job_id,
                f"Something went wrong while reading that page ({type(error).__name__}).")
    results.put(message)

class SiphonApp(ttk.Window):
    def __init__(self) -> None:
        super().__init__(title="siphon.", themename=LIGHT_THEME, size=(1000, 640), minsize=(760, 480))

        self.url_var = ttk.StringVar()
        self.status_var = ttk.StringVar(value=READY_TEXT)
        self.status_is_error = False

        self.tables: list[Table] = [] # what the last successful fetch found
        self.busy = False # True while a download is running
        self._results: queue.Queue = queue.Queue() # worker -> window messages
        self._cancel_event: threading.Event | None = None
        self._job_id = 0   # lets us ignore answers from cancelled jobs
        self._poll_id = None  # the pending "check for news" timer

        self.columnconfigure(0, weight=1) # the middle row stretches with the window
        self.rowconfigure(1, weight=1)
        self._build_top_bar()
        self._build_content()
        self._build_status_bar()

        self.bind("<Control-l>", lambda event: self._focus_url()) # like a browser's address bar
        self.bind("<Escape>", lambda event: self.on_cancel())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._focus_url)

#layout
    def _build_top_bar(self) -> None:
        bar = ttk.Frame(self, padding=PAD)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1) # the URL box takes all the spare width

        ttk.Label(bar, text="URL").grid(row=0, column=0, padx=(0, 8))
        self.url_entry = ttk.Entry(bar, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        self.url_entry.bind("<Return>", lambda event: self.on_fetch())

        self.fetch_button = ttk.Button(bar, text="Fetch", bootstyle="primary", command=self.on_fetch)
        self.fetch_button.grid(row=0, column=2, padx=(8, 0))

        self.cancel_button = ttk.Button(bar, text="Cancel", bootstyle="danger-outline",
                                        command=self.on_cancel, state="disabled")
        self.cancel_button.grid(row=0, column=3, padx=(8, 0))

        # [CHANGED] column was 3, now 4 to make room for Cancel
        self.theme_button = ttk.Button(bar, text="Dark", width=6, bootstyle="secondary-outline",
                                    command=self.toggle_theme)
        self.theme_button.grid(row=0, column=4, padx=(8, 0))

    def _build_content(self) -> None:
        self.content = ttk.Frame(self, padding=PAD)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self.table_view = TableView(self.content, notify=self.set_status)
        self.table_view.grid(row=0, column=0, sticky="nsew")

    def _build_status_bar(self) -> None:
        ttk.Separator(self).grid(row=2, column=0, sticky="ew")
        bar = ttk.Frame(self)
        bar.grid(row=3, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(bar, textvariable=self.status_var, padding=(PAD, 8), anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=1, padx=(0, PAD))
        self.progress.grid_remove()# hidden until a download starts

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
        mode = self.style.toggle_theme() # switches bootstrap-light <-> bootstrap-dark
        self.theme_button.configure(text="Light" if mode == "dark" else "Dark")   # offer the other one

    def on_fetch(self) -> None:
        if self.busy:# Enter pressed twice must not start two downloads
            return
        try:
            url = normalize_url(self.url_var.get())
        except FetchError as error:
            self.set_status(str(error), error=True)
            return
        self.url_var.set(url) # show the tidied address back to the user
        self._start_job(url)

#background work
    def _start_job(self, url: str) -> None:
        self._job_id += 1
        self._cancel_event = threading.Event()
        self._set_busy(True)
        self.set_status(f"Downloading from {urlparse(url).hostname} ...")
        threading.Thread(target=run_job, args=(self._results, self._job_id, url, self._cancel_event),
                        daemon=True).start()      # daemon: it can't keep the program alive
        self._schedule_poll()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.fetch_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.grid()
            self.progress.start(15)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def _schedule_poll(self) -> None:
        if self._poll_id is not None:# never run two pollers at once
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
            self._show_tables(message[2])
        elif kind == "error":
            self.set_status(message[2], error=True)
        else: # "cancelled"
            self.set_status("Cancelled.")

    def on_cancel(self) -> None:
        if not self.busy:
            return
        self._cancel_event.set() # ask the worker to stop as soon as it can
        self._job_id += 1 # whatever it sends back from now on is ignored
        self._set_busy(False) # and the window is free again straight away
        self.set_status("Cancelled.")

    def _show_tables(self, tables: list[Table]) -> None:
        self.tables = tables
        if not tables:
            self.table_view.set_tables([], "No tables found on that page.")
            self.set_status("No tables found on that page. It may load its data with JavaScript.")
            return
        self.table_view.set_tables(tables)
        word = "table" if len(tables) == 1 else "tables"
        text = f"Found {len(tables)} {word}"
        layout = sum(1 for table in tables if table.is_layout)
        if layout:
            text += f" ({layout} look{'s' if layout == 1 else ''} like page layout)"
        self.set_status(text + ".")

    def on_close(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set() # tell a running download to give up
        self.destroy()

def main() -> None:
    SiphonApp().mainloop()

if __name__ == "__main__":
    main()