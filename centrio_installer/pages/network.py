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
        super().__init__(title="Network &amp; Hostname", subtitle="Configure hostname", main_window=main_window, overlay_widget=overlay_widget, **kwargs)
        # No D-Bus proxy needed
        # self.network_proxy = None 
        self.current_hostname = "localhost.localdomain" # Default

        # --- UI Setup --- 
        net_group = Adw.PreferencesGroup()
        self.add(net_group)
        self.hostname_row = Adw.EntryRow(title="Hostname")
        self.hostname_row.set_text(self.current_hostname) # Set default initially
        net_group.add(self.hostname_row)
        
        # Keep network config placeholder for now
        info_row = Adw.ActionRow(title="Network Configuration", 
                                   subtitle="Requires NetworkManager integration (Not Implemented)")
        info_row.set_activatable(False)
        net_group.add(info_row)

        # --- Confirmation Button --- 
        button_group = Adw.PreferencesGroup()
        self.add(button_group)
        self.complete_button = Gtk.Button(label="Apply Hostname")
        self.complete_button.set_halign(Gtk.Align.CENTER)
        self.complete_button.set_margin_top(24)
        self.complete_button.add_css_class("suggested-action")
        self.complete_button.connect("clicked", self.apply_settings_and_return)
        # Enable by default, disable on error during fetch/apply
        self.complete_button.set_sensitive(True)
        self.hostname_row.set_sensitive(True)
        button_group.add(self.complete_button)

        # --- Fetch Data --- 
        self.connect_and_fetch_data()
        
    def connect_and_fetch_data(self):
        """Fetches the current hostname using socket."""
        print("Fetching current hostname using socket...")
        try:
            # Get the standard hostname
            self.current_hostname = socket.gethostname()
            # For display, often the fully qualified name is preferred if available
            # Try getting FQDN, fallback to standard hostname
            try:
                fqdn = socket.getfqdn()
                if fqdn and "." in fqdn: # Basic check if it looks like FQDN
                    self.current_hostname = fqdn
            except socket.gaierror:
                pass # Ignore if FQDN lookup fails

            print(f"Fetched Hostname: {self.current_hostname}")
            self.hostname_row.set_text(self.current_hostname)
            self.hostname_row.set_sensitive(True)
            self.complete_button.set_sensitive(True)
            
        except Exception as e:
            print(f"ERROR: Failed to get hostname: {e}")
            self.show_toast(f"Failed to retrieve current hostname: {e}")
            # Keep default, disable UI elements
            self.hostname_row.set_text(self.current_hostname) # Show the default
            self.hostname_row.set_sensitive(False)
            self.complete_button.set_sensitive(False)

    def apply_settings_and_return(self, button):
        """Applies the hostname using hostnamectl."""
        hostname = self.hostname_row.get_text().strip()
        if not hostname:
             self.show_toast("Hostname cannot be empty.")
             return
        
        # Basic validation: prevent setting purely numeric hostname, etc.
        # A more robust check would use regex or a library.
        if hostname.isdigit() or len(hostname) > 63 or not hostname.replace('.','').isalnum():
             self.show_toast("Invalid hostname format.")
             return
             
        print(f"Attempting to set hostname to '{hostname}' using hostnamectl...")
        self.complete_button.set_sensitive(False) # Disable during operation
        self.hostname_row.set_sensitive(False)
        
        cmd = ["hostnamectl", "set-hostname", hostname]
        
        try:
            # Run hostnamectl set-hostname
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
            print(f"hostnamectl output: {result.stdout}")
            print(f"Hostname set successfully to {hostname}")
            self.show_toast(f"Hostname set to '{hostname}' successfully!")
            # Pass the applied hostname back
            config_values = {"hostname": hostname}
            super().mark_complete_and_return(button, config_values=config_values)
            
        except FileNotFoundError:
            print("ERROR: hostnamectl command not found.")
            self.show_toast("Error: hostnamectl command not found. Cannot set hostname.")
            # Re-enable UI on error
            self.hostname_row.set_sensitive(True)
            self.complete_button.set_sensitive(True) 
        except subprocess.CalledProcessError as e:
            print(f"ERROR: hostnamectl set-hostname failed (Exit code: {e.returncode}):")
            print(f"Stderr: {e.stderr}")
            print(f"Stdout: {e.stdout}")
            # Try to show a more specific error if possible
            error_msg = e.stderr.strip() or f"hostnamectl failed with exit code {e.returncode}"
            self.show_toast(f"Error setting hostname: {error_msg}")
            self.hostname_row.set_sensitive(True)
            self.complete_button.set_sensitive(True) 
        except subprocess.TimeoutExpired:
            print("ERROR: hostnamectl command timed out.")
            self.show_toast("Setting hostname timed out.")
            self.hostname_row.set_sensitive(True)
            self.complete_button.set_sensitive(True) 
        except Exception as e:
            print(f"ERROR: Unexpected error setting hostname: {e}")
            self.show_toast(f"An unexpected error occurred while setting hostname.")
            self.hostname_row.set_sensitive(True)
            self.complete_button.set_sensitive(True) 