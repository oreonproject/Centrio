import gi
import subprocess 
import shlex      
import crypt # Import crypt for hashing
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from .base import BaseConfigurationPage

class UserPage(BaseConfigurationPage):
    def __init__(self, main_window, overlay_widget, **kwargs):
        super().__init__(title="User Creation", subtitle="Create an initial user account", main_window=main_window, overlay_widget=overlay_widget, **kwargs)
        
        # --- Create UI Elements FIRST ---
        details_group = Adw.PreferencesGroup(title="User Details")
        self.add(details_group)
        self.real_name_row = Adw.EntryRow(title="Full Name")
        details_group.add(self.real_name_row)
        self.username_row = Adw.EntryRow(title="Username")
        details_group.add(self.username_row)
        
        password_group = Adw.PreferencesGroup(title="Password")
        self.add(password_group)
        self.password_row = Adw.PasswordEntryRow(title="Password")
        password_group.add(self.password_row)
        self.confirm_password_row = Adw.PasswordEntryRow(title="Confirm Password")
        password_group.add(self.confirm_password_row)
        
        # Add admin checkbox (optional)
        admin_group = Adw.PreferencesGroup(title="Administrator Privileges")
        self.add(admin_group)
        self.admin_check = Gtk.CheckButton(label="Make this user an administrator")
        self.admin_check.set_tooltip_text("Adds the user to the 'wheel' group for sudo access")
        self.admin_check.set_active(True) # Default to admin
        admin_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        admin_box.set_halign(Gtk.Align.CENTER)
        admin_box.set_valign(Gtk.Align.CENTER)
        admin_box.append(self.admin_check)
        admin_group.add(admin_box)
        
        button_group = Adw.PreferencesGroup()
        self.add(button_group)
        self.complete_button = Gtk.Button(label="Create User Account") 
        self.complete_button.set_halign(Gtk.Align.CENTER)
        self.complete_button.set_margin_top(24)
        self.complete_button.add_css_class("suggested-action")
        button_group.add(self.complete_button)

        # --- Connect Signals for Validation ---
        self.username_row.connect("notify::text", self.validate_input)
        self.password_row.connect("notify::text", self.validate_input)
        self.confirm_password_row.connect("notify::text", self.validate_input)
        self.complete_button.connect("clicked", self.apply_settings_and_return)

        # --- Initial Validation ---
        self.validate_input()

            
    def connect_and_fetch_data(self):
         # Nothing to fetch for user creation
         pass 

    def validate_input(self, widget=None, param=None):
        """Validate user input fields and update button sensitivity."""
        if not all(hasattr(self, attr) for attr in ['username_row', 'password_row', 'confirm_password_row', 'complete_button']):
             print("UserPage validate_input called before UI fully initialized - skipping validation.")
             return
             
        username = self.username_row.get_text().strip()
        password = self.password_row.get_text()
        confirm = self.confirm_password_row.get_text()
        
        # Basic username validation (more robust needed for production)
        valid_user = bool(username) and username.islower() and username.isalnum() and len(username) < 32
        # Password must not be empty and must match confirmation
        valid_password = bool(password) and password == confirm 
        can_apply = valid_user and valid_password

        # Visual feedback for password mismatch
        if password and confirm and password != confirm:
            self.password_row.add_css_class("error")
            self.confirm_password_row.add_css_class("error")
        else:
            self.password_row.remove_css_class("error")
            self.confirm_password_row.remove_css_class("error")
            
        self.complete_button.set_sensitive(can_apply)

    def apply_settings_and_return(self, button):
        """Validates input, hashes password, and passes user details back."""
        self.validate_input()
        if not self.complete_button.get_sensitive():
             self.show_toast("Please ensure username is valid and passwords match and are not empty.")
             return
             
        real_name = self.real_name_row.get_text().strip()
        username = self.username_row.get_text().strip()
        password = self.password_row.get_text()
        is_admin = self.admin_check.get_active()

        # --- Hash the password --- 
        try:
            # Use SHA512 for modern compatibility
            hashed_password = crypt.crypt(password, crypt.METHOD_SHA512)
            print(f"Password hashed successfully for user {username}.")
        except Exception as e:
             # Handle potential errors during hashing (e.g., crypt unavailable? unlikely with stdlib)
             print(f"ERROR: Password hashing failed: {e}")
             self.show_toast(f"Password hashing failed: {e}")
             return

        print(f"--- Confirming User Details ---")
        print(f"  Username:  {username}")
        print(f"  Full Name: {real_name}")
        print(f"  Password:  (Hashed)") 
        print(f"  Admin:     {is_admin}")
        
        config_values = {
            "username": username, 
            "real_name": real_name, 
            "hashed_password": hashed_password, # Store the hash
            "is_admin": is_admin
        }
        
        self.show_toast(f"User details for '{username}' confirmed.")
        super().mark_complete_and_return(button, config_values=config_values) 