"""
siphon_app/gui/app.py

The main window: a URL bar, a place for the tables, and a status bar.
This step only builds the window and the theme switch; fetching, the table
list and exporting are added in later steps.
"""
import ttkbootstrap as ttk

from siphon_app.core.fetcher import FetchError, normalize_url

LIGHT_THEME = "bootstrap-light" #ttkbootstrap 2.x ships matching -light/ -dark pairs
PAD = 12 #space around things, in pixels

READY_TEXT = "Paste a link to a page with tables, then press Fetch."

class SiphonApp(ttk.Window):
    def __init__(self) -> None:
        super().__init__(title="siphon.", themename=LIGHT_THEME, size=(1000, 640), minsize=(760, 480))
        
        self.url_var = ttk.StringVar()
        self.status_var = ttk.StringVar(value=READY_TEXT)
        self.status_is_error = False
        
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_top_bar()
        self._build_content()
        self._build_status_bar()
        
        self.bind("<Control-l>", lambda event: self._focus_url())
        self.after(100, self._focus_url)

#the layout
    def _build_top_bar(self) -> None:
        bar = ttk.Frame(self, padding=PAD)
        bar.grid(row = 0, column = 0, sticky = "ew")
        bar.columnconfigure(1, weight=1)
        
        ttk.Label(bar, text="URL").grid(row = 0, column = 0, padx = (0, 8))
        self.url_entry = ttk.Entry(bar, textvariable=self.url_var)
        self.url_entry.grid(row = 0, column = 1, sticky = "ew")
        self.url_entry.bind("<Return>", lambda event: self.on_fetch())
        
        self.fetch_button = ttk.Button(bar, text="Fetch", bootstyle="primary", command=self.on_fetch)
        self.fetch_button.grid(row=0, column=2, padx = (8, 0))
        
        self.theme_button = ttk.Button(bar, text="Dark", width=6, bootstyle="secondary-outline",
                                    command=self.toggle_theme)
        self.theme_button.grid(row=0, column=3, padx=(8, 0))
    
    def _build_content(self) -> None:
        self.content = ttk.Frame(self, padding=PAD)
        self.content.grid(row=1, column = 0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        ttk.Label(self.content, text="Tables will show up here.", bootstyle="secondary",
                anchor="center").grid(row=0, column=0, sticky="nsew")
    
    def _build_status_bar(self) -> None:
        ttk.Separator(self).grid(row=2, column=0, sticky="ew")
        self.status_label = ttk.Label(self, textvariable=self.status_var, padding=(PAD, 8), anchor="w")
        self.status_label.grid(row=3, column=0, sticky="ew")

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
        mode = self.style.toggle_theme()           # switches bootstrap-light <-> bootstrap-dark
        self.theme_button.configure(text="Light" if mode == "dark" else "Dark")    # offer the other one

    def on_fetch(self) -> None:
        # Step 6 only checks the address. Step 7 replaces this with the real download.
        try:
            url = normalize_url(self.url_var.get())
        except FetchError as error:
            self.set_status(str(error), error=True)
            return
        self.url_var.set(url)                      # show the tidied address back to the user
        self.set_status(f"Ready to fetch {url}  (downloading is added in the next step)")

def main() -> None:
    SiphonApp().mainloop()

if __name__ == "__main__":
    main()