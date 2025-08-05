# centrio_installer/ui/network.py

import gi
import subprocess
import threading
import time
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from .base import BaseConfigurationPage

class NetworkConnectivityPage(BaseConfigurationPage):
    """Page for configuring network connectivity for additional package installation."""
    
    def __init__(self, main_window, overlay_widget, **kwargs):
        super().__init__(
            title="Network Connectivity", 
            subtitle="Configure network for additional software installation", 
            main_window=main_window, 
            overlay_widget=overlay_widget, 
            **kwargs
        )
        
        # State variables
        self.network_enabled = False
        self.network_configured = False
        self.skip_network = False
        self.network_status = "unknown"
        self.connection_test_running = False
        
        self._build_ui()
        self._check_network_status()
        
    def _build_ui(self):
        """Build the network connectivity UI."""
        
        # Network Status Section
        self.status_section = Adw.PreferencesGroup(
            title="Network Status",
            description="Current network connectivity status"
        )
        self.add(self.status_section)
        
        # Network status row
        self.status_row = Adw.ActionRow(
            title="Network Status",
            subtitle="Checking network connectivity..."
        )
        self.status_icon = Gtk.Image.new_from_icon_name("network-wireless-symbolic")
        self.status_row.add_prefix(self.status_icon)
        self.status_section.add(self.status_row)
        
        # Network Configuration Section
        self.config_section = Adw.PreferencesGroup(
            title="Network Configuration",
            description="Configure network for additional software installation"
        )
        self.add(self.config_section)
        
        # Enable network for additional packages
        self.enable_network_row = Adw.SwitchRow(
            title="Enable Network for Additional Packages",
            subtitle="Allow installation of extra software from repositories"
        )
        self.enable_network_row.set_active(self.network_enabled)
        self.enable_network_row.connect("notify::active", self.on_network_toggled)
        self.config_section.add(self.enable_network_row)
        
        # Skip network option
        self.skip_network_row = Adw.SwitchRow(
            title="Skip Network Configuration",
            subtitle="Install only the base system without additional packages"
        )
        self.skip_network_row.set_active(self.skip_network)
        self.skip_network_row.connect("notify::active", self.on_skip_toggled)
        self.config_section.add(self.skip_network_row)
        
        # Network Test Section
        self.test_section = Adw.PreferencesGroup(
            title="Network Test",
            description="Test network connectivity to repositories"
        )
        self.add(self.test_section)
        
        # Test connection button
        self.test_button = Gtk.Button(label="Test Network Connection")
        self.test_button.set_valign(Gtk.Align.CENTER)
        self.test_button.connect("clicked", self.test_network_connection)
        self.test_section.add(self.test_button)
        
        # Test results
        self.test_result_row = Adw.ActionRow(
            title="Connection Test Results",
            subtitle="Click 'Test Network Connection' to check connectivity"
        )
        self.test_section.add(self.test_result_row)
        
        # Information Section
        self.info_section = Adw.PreferencesGroup(
            title="Information",
            description="About network connectivity and package installation"
        )
        self.add(self.info_section)
        
        # Info text
        info_text = """The live environment will be copied to disk regardless of network status.

If you enable network connectivity, you can install additional software like:
• Web browsers (Firefox, Chrome)
• Office applications (LibreOffice)
• Development tools
• Gaming applications
• And more via Flatpak

If you skip network configuration, only the base system will be installed."""
        
        info_label = Gtk.Label(label=info_text)
        info_label.set_wrap(True)
        info_label.set_xalign(0.0)
        info_label.add_css_class("dim-label")
        self.info_section.add(info_label)
        
        # Confirm button
        self.button_section = Adw.PreferencesGroup()
        self.add(self.button_section)
        
        confirm_row = Adw.ActionRow(
            title="Confirm Network Configuration",
            subtitle="Review and apply your network settings"
        )
        self.complete_button = Gtk.Button(label="Apply Network Settings")
        self.complete_button.set_valign(Gtk.Align.CENTER)
        self.complete_button.add_css_class("suggested-action")
        self.complete_button.connect("clicked", self.apply_settings_and_return)
        confirm_row.add_suffix(self.complete_button)
        self.button_section.add(confirm_row)
        
    def _check_network_status(self):
        """Check current network status."""
        def check_network():
            try:
                # Test basic connectivity
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", "5", "8.8.8.8"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    self.network_status = "connected"
                    GLib.idle_add(self._update_network_status, "connected", "Network is available")
                else:
                    self.network_status = "disconnected"
                    GLib.idle_add(self._update_network_status, "disconnected", "No network connectivity detected")
                    
            except Exception as e:
                self.network_status = "unknown"
                GLib.idle_add(self._update_network_status, "unknown", f"Could not check network: {e}")
        
        thread = threading.Thread(target=check_network)
        thread.daemon = True
        thread.start()
        
    def _update_network_status(self, status, message):
        """Update the network status display."""
        self.network_status = status
        
        if status == "connected":
            self.status_row.set_subtitle("Network is available")
            self.status_icon.set_from_icon_name("network-wireless-symbolic")
            self.status_icon.add_css_class("success")
            self.enable_network_row.set_sensitive(True)
        elif status == "disconnected":
            self.status_row.set_subtitle("No network connectivity")
            self.status_icon.set_from_icon_name("network-offline-symbolic")
            self.status_icon.add_css_class("error")
            self.enable_network_row.set_sensitive(False)
            self.enable_network_row.set_active(False)
        else:
            self.status_row.set_subtitle("Network status unknown")
            self.status_icon.set_from_icon_name("network-wireless-symbolic")
            self.status_icon.add_css_class("warning")
            self.enable_network_row.set_sensitive(True)
            
    def on_network_toggled(self, switch_row, pspec):
        """Handle network enable toggle."""
        self.network_enabled = switch_row.get_active()
        if self.network_enabled:
            self.skip_network_row.set_active(False)
            self.skip_network = False
        print(f"Network enabled: {self.network_enabled}")
        
    def on_skip_toggled(self, switch_row, pspec):
        """Handle skip network toggle."""
        self.skip_network = switch_row.get_active()
        if self.skip_network:
            self.enable_network_row.set_active(False)
            self.network_enabled = False
        print(f"Skip network: {self.skip_network}")
        
    def test_network_connection(self, button):
        """Test network connectivity to repositories."""
        if self.connection_test_running:
            return
            
        self.connection_test_running = True
        self.test_button.set_sensitive(False)
        self.test_result_row.set_subtitle("Testing connection...")
        
        def run_test():
            try:
                # Test DNS resolution
                dns_result = subprocess.run(
                    ["nslookup", "dl.flathub.org"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                # Test HTTP connectivity
                http_result = subprocess.run(
                    ["curl", "-I", "--connect-timeout", "10", "https://dl.flathub.org"],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                
                if dns_result.returncode == 0 and http_result.returncode == 0:
                    result_message = "✓ Network connectivity test passed"
                    result_status = "success"
                else:
                    result_message = "✗ Network connectivity test failed"
                    result_status = "error"
                    
            except Exception as e:
                result_message = f"✗ Network test error: {e}"
                result_status = "error"
                
            GLib.idle_add(self._update_test_result, result_message, result_status)
            
        thread = threading.Thread(target=run_test)
        thread.daemon = True
        thread.start()
        
    def _update_test_result(self, message, status):
        """Update the test result display."""
        self.test_result_row.set_subtitle(message)
        self.connection_test_running = False
        self.test_button.set_sensitive(True)
        
        if status == "success":
            self.test_button.add_css_class("success")
        else:
            self.test_button.add_css_class("error")
            
    def _get_page_key(self):
        """Override to return the correct page key."""
        return "network"
        
    def apply_settings_and_return(self, button):
        """Apply the network configuration and return to summary."""
        print(f"--- Apply Network Settings START ---")
        
        print(f"  Network enabled: {self.network_enabled}")
        print(f"  Skip network: {self.skip_network}")
        print(f"  Network status: {self.network_status}")
        
        # Build configuration data
        config_values = {
            "network_enabled": self.network_enabled,
            "skip_network": self.skip_network,
            "network_status": self.network_status
        }
        
        # Show confirmation message
        if self.skip_network:
            message = "Network configuration skipped - only base system will be installed"
        elif self.network_enabled:
            message = "Network enabled - additional packages can be installed"
        else:
            message = "Network disabled - only base system will be installed"
            
        self.show_toast(message)
        
        print("Network configuration confirmed. Returning to summary.")
        super().mark_complete_and_return(button, config_values=config_values) 