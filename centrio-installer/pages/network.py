# centrio_installer/pages/network.py

import gi
import socket     # For getting current hostname
import subprocess # For running hostnamectl
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from .base import BaseConfigurationPage
# D-Bus utils/constants no longer needed
# from ..utils import dasbus, DBusError, dbus_available 
# from ..constants import (...) 

class NetworkPage(BaseConfigurationPage):
    def __init__(self, main_window, overlay_widget, **kwargs):
        super().__init__(title="Network &amp; Hostname", subtitle="Configure hostname for the installed system", main_window=main_window, overlay_widget=overlay_widget, **kwargs)
        # No D-Bus proxy needed
        # self.network_proxy = None 
        self.default_hostname = "Centrio" # Define default

        # --- UI Setup --- 
        net_group = Adw.PreferencesGroup()
        self.add(net_group)
        self.hostname_row = Adw.EntryRow(title="Target Hostname")
        # Initialize with default
        self.hostname_row.set_text(self.default_hostname) 
        net_group.add(self.hostname_row)
        
        # Keep network config placeholder for now
        info_row = Adw.ActionRow(title="Network Configuration", 
                                   subtitle="Requires NetworkManager integration (Not Implemented)")
        info_row.set_activatable(False)
        net_group.add(info_row)

        # --- Confirmation Button --- 
        button_group = Adw.PreferencesGroup()
        self.add(button_group)
        # Changed button label to reflect saving, not immediate application
        self.complete_button = Gtk.Button(label="Confirm Hostname") 
        self.complete_button.set_halign(Gtk.Align.CENTER)
        self.complete_button.set_margin_top(24)
        self.complete_button.add_css_class("suggested-action")
        self.complete_button.connect("clicked", self.save_settings_and_return) # Renamed handler
        # Enable by default, disable on error during fetch/apply
        self.complete_button.set_sensitive(True)
        self.hostname_row.set_sensitive(True)
        button_group.add(self.complete_button)

        # --- Fetch Configured Data --- 
        self.fetch_configured_data()
        
    def fetch_configured_data(self):
        """Fetches the previously configured hostname from main window's final_config."""
        print("Fetching configured hostname from main_window.final_config...")
        try:
            # Access final_config directly on main_window
            network_config = self.main_window.final_config.get('network', {}) 
            configured_hostname = network_config.get('hostname')
            
            if configured_hostname:
                print(f"Found configured hostname: {configured_hostname}")
                self.hostname_row.set_text(configured_hostname)
            else:
                print(f"No configured hostname found, using default: {self.default_hostname}")
                self.hostname_row.set_text(self.default_hostname)

            self.hostname_row.set_sensitive(True)
            self.complete_button.set_sensitive(True)
            
        except Exception as e:
            # Use AttributeError specifically? Or keep broad catch?
            print(f"ERROR: Failed to get configured hostname from final_config: {e}")
            self.show_toast(f"Failed to retrieve configured hostname: {e}")
            self.hostname_row.set_text(self.default_hostname) 

    # Renamed function to reflect action
    def save_settings_and_return(self, button): 
        """Validates hostname and calls mark_complete_and_return to save it."""
        hostname = self.hostname_row.get_text().strip()
        if not hostname:
             self.show_toast("Hostname cannot be empty.")
             return
        
        # Basic validation (keep existing checks)
        if hostname.isdigit() or len(hostname) > 63 or not hostname.replace('.','').replace('-','').isalnum(): # Allow hyphens
             # Refined check for common hostname rules (simple version)
             # - Max 63 chars per label (not checked here fully)
             # - Max 253 total chars (not checked)
             # - Start/End with letter/digit
             # - Contain only letters, digits, hyphens
             # - Cannot be all numeric
             import re
             if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?))*$", hostname) or hostname.isdigit():
                  self.show_toast("Invalid hostname format. Use letters, numbers, hyphens. Max 63 chars.")
                  return
             
        print(f"Confirming hostname '{hostname}'...")
        config_values = {"hostname": hostname}
        # Remove direct update - mark_complete_and_return handles storage via main_window.mark_config_complete
        # self.main_window.config_manager.update_section("network", config_values)
        # print("Hostname configuration saved.") 
        self.show_toast(f"Hostname '{hostname}' confirmed.")
        
        # Mark complete and return (passing saved values)
        super().mark_complete_and_return(button, config_values=config_values) 