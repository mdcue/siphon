"""
siphon_app/gui/dialogs.py

Small pop-up boxes. ask_name shows one text field and gives back what the person
typed, or None if they cancelled.
"""
import ttkbootstrap as ttk


class NameDialog(ttk.Toplevel):
    def __init__(self, parent, current: str = "") -> None:
        # master=parent matters: ttkbootstrap's first positional argument is the TITLE,
        # not the parent, so the parent has to be passed by name.
        super().__init__(title="Rename column", resizable=(False, False),
                         transient=parent.winfo_toplevel(), master=parent)
        self.result: str | None = None      # stays None unless they press Rename

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="New name for this column").pack(anchor="w")
        self.value = ttk.StringVar(value=current)
        self.entry = ttk.Entry(frame, textvariable=self.value, width=36)
        self.entry.pack(fill="x", pady=(6, 12))
        self.entry.focus_set()
        self.entry.select_range(0, "end")       # the old name is selected, so typing replaces it

        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e")
        self.cancel_button = ttk.Button(buttons, text="Cancel", bootstyle="secondary-outline",
                                        command=self.cancel)
        self.cancel_button.pack(side="left")
        self.ok_button = ttk.Button(buttons, text="Rename", command=self.accept)
        self.ok_button.pack(side="left", padx=(8, 0))
        self.bind("<Return>", lambda event: self.accept())      # Enter = Rename
        self.bind("<Escape>", lambda event: self.cancel())      # Esc = Cancel

    def accept(self) -> None:
        self.result = self.value.get()
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()


def ask_name(parent, current: str = "") -> str | None:
    """Show the box, wait until it closes, then return the typed name (or None)."""
    dialog = NameDialog(parent, current)
    dialog.grab_set()           # modal: the main window ignores clicks until this is closed
    dialog.wait_window()
    return dialog.result
