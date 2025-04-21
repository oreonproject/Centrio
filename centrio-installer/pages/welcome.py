# centrio_installer/pages/welcome.py

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

# Import the utility function
from ..utils import get_os_release_info

class WelcomePage(Gtk.Box):
    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, **kwargs)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(48)
        self.set_margin_end(48)

        # Get OS Name
        os_info = get_os_release_info()
        distro_name = os_info.get("NAME", "Linux") # Default to Linux if NAME not found
        
        # Use OS Name in title
        title_text = f"Welcome to {distro_name}! Let's get started."
        title = Gtk.Label(label=title_text)
        title.add_css_class("title-1")
        self.append(title)

        lang_label = Gtk.Label(label="Select Installer Language:", halign=Gtk.Align.START)
        self.append(lang_label)

        lang_combo = Gtk.ComboBoxText()
        # TODO: Get actual supported UI languages
        langs = [("en", "English (US)"), ("es", "Español"), ("fr", "Français"), ("de", "Deutsch")]
        default_index = 0
        for i, (code, name) in enumerate(langs):
            lang_combo.append(code, name)
            if code == "en":
                 default_index = i
                 
        lang_combo.set_active(default_index)
        lang_combo.connect("changed", self.on_language_changed)
        self.append(lang_combo)

        info_label = Gtk.Label(label="\nThis wizard will guide you through the installation process.")
        info_label.set_wrap(True)
        self.append(info_label)

    def on_language_changed(self, combo):
        active_id = combo.get_active_id()
        print(f"Language selected: {active_id}")
        # TODO: Implement actual language switching (gettext) 