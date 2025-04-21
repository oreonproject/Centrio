# centrio_installer/pages/payload.py

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from .base import BaseConfigurationPage
# Removed D-Bus imports
# from ..utils import dasbus, DBusError, dbus_available 
# from ..constants import (...) 

class PayloadPage(BaseConfigurationPage):
    """Page for Payload (Installation Source) Configuration (Placeholder)."""
    def __init__(self, main_window, overlay_widget, **kwargs):
        super().__init__(title="Installation Source", subtitle="Configure package source (Defaults Used)", main_window=main_window, overlay_widget=overlay_widget, **kwargs)
        # Removed D-Bus proxy variables
        self.payload_type = "DNF" # Assume DNF for now

        # No D-Bus connection needed
        # self._connect_dbus() 

        # --- UI Elements (Informational Only) ---
        info_group = Adw.PreferencesGroup()
        self.add(info_group)
        info_label = Gtk.Label(label=f"Using default payload type: {self.payload_type}.\n\nPackage selection and source repository configuration\nwill be handled automatically during the installation process.\n(No configuration needed here for this installer version)." )
        info_label.set_wrap(True)
        info_label.set_margin_top(12)
        info_label.set_margin_bottom(12)
        info_group.add(info_label)

        # --- Confirmation Button --- 
        button_group = Adw.PreferencesGroup()
        self.add(button_group)
        self.complete_button = Gtk.Button(label="Confirm Payload Choice")
        self.complete_button.set_halign(Gtk.Align.CENTER)
        self.complete_button.set_margin_top(24)
        self.complete_button.add_css_class("suggested-action")
        self.complete_button.connect("clicked", self.apply_settings_and_return) 
        self.complete_button.set_sensitive(True) # Always enabled as it's just confirmation
        button_group.add(self.complete_button)
        
    # Removed _connect_dbus method
            
    def connect_and_fetch_data(self):
        # Nothing to fetch in this placeholder version
         pass 
         
    def apply_settings_and_return(self, button):
        """Confirms the intent to use the default payload type."""
        print(f"Payload configuration confirmed: Using type '{self.payload_type}'")
        self.show_toast(f"Default payload ({self.payload_type}) confirmed.")
        
        # Pass back the intended payload type
        config_values = {
            "payload_type": self.payload_type,
        }
        super().mark_complete_and_return(button, config_values=config_values) 