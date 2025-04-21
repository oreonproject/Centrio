# centrio_installer/pages/finished.py

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

class FinishedPage(Gtk.Box):
    def __init__(self, app, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18, **kwargs)
        self.app = app
        self.set_margin_top(36)
        self.set_margin_bottom(36)
        self.set_margin_start(48)
        self.set_margin_end(48)
        self.set_valign(Gtk.Align.CENTER)
        self.set_vexpand(True)

        title = Gtk.Label(label="Installation Complete")
        title.add_css_class("title-1")
        self.append(title)

        info_label = Gtk.Label(label="Centrio has been installed on your system. Please remove the installation media and restart your computer.")
        info_label.set_wrap(True)
        self.append(info_label)

        reboot_button = Gtk.Button(label="Reboot Now")
        reboot_button.add_css_class("destructive-action") 
        reboot_button.set_halign(Gtk.Align.CENTER)
        reboot_button.connect("clicked", self.on_reboot)
        self.append(reboot_button)

    def on_reboot(self, button):
        print("Reboot requested! (Simulated)")
        # In a real scenario, this would trigger a system reboot command
        # For safety in this simulation, we just quit the app.
        self.app.quit() 