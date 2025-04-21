# centrio_installer/pages/summary.py

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw


class SummaryPage(Adw.PreferencesPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(title="Installation Summary", **kwargs)
        self.main_window = main_window
        self.config_rows = {}

        # --- Localization Group ---
        loc_group = Adw.PreferencesGroup(title="Localization")
        self.add(loc_group)
        self._add_config_row(loc_group, "keyboard", "Keyboard", "Keyboard layout", True)
        self._add_config_row(loc_group, "language", "System Language", "Set the default system locale", False)

        # --- System Group ---
        sys_group = Adw.PreferencesGroup(title="System")
        self.add(sys_group)
        self._add_config_row(sys_group, "timedate", "Time &amp; Date", "Timezone and time settings", True)
        self._add_config_row(sys_group, "disk", "Installation Destination", "Disk selection and partitioning", True)
        self._add_config_row(sys_group, "network", "Network &amp; Host Name", "Network configuration", True)
        # Add Payload row (required)
        self._add_config_row(sys_group, "payload", "Installation Source", "Package source selection", True)
        # Add Bootloader row (required)
        self._add_config_row(sys_group, "bootloader", "Bootloader", "Bootloader configuration", True)

        # --- User Settings Group ---
        user_group = Adw.PreferencesGroup(title="User Settings")
        self.add(user_group)
        self._add_config_row(user_group, "user", "User Creation", "Create user accounts", False)

        # Add informational text inside a group
        info_group = Adw.PreferencesGroup() 
        self.add(info_group) 
        info_label = Gtk.Label(label="\nPlease configure the items marked with ⚠ before proceeding.")
        info_label.set_halign(Gtk.Align.CENTER)
        info_label.set_margin_top(12)
        info_label.set_margin_bottom(12) # Add bottom margin too
        info_group.add(info_label)

    def _add_config_row(self, group, key, title, subtitle_base, required):
        row = Adw.ActionRow(title=title)
        row.set_activatable(True)
        row.connect("activated", self.on_row_activated, key)
        # Initialize config_state in main window if not already present
        # This ensures even rows added later get tracked
        if key not in self.main_window.config_state:
             self.main_window.config_state[key] = False
             
        self.config_rows[key] = {
            "row": row, 
            "required": required, 
            "subtitle_base": subtitle_base,
            "icon_widget": None 
        }
        group.add(row)
        # Update row status based on initial state from main_window
        self.update_row_status(key, self.main_window.config_state.get(key, False))

    def on_row_activated(self, row, key):
        self.main_window.navigate_to_config(key)

    def update_row_status(self, key, is_complete):
        if key not in self.config_rows:
            print(f"Warning: Attempted to update status for unknown row key: {key}")
            return
        config = self.config_rows[key]
        row = config["row"]
        subtitle = config["subtitle_base"]
        icon_name = None
        new_icon_widget = None
        tooltip_text = None # For debugging

        # Determine icon and subtitle based on state
        if is_complete:
            row.set_subtitle(f"{subtitle} (Completed)")
            icon_name = "emblem-ok-symbolic"
            tooltip_text = "Completed"
        elif config["required"]:
            row.set_subtitle(f"{subtitle} (Configuration required)")
            icon_name = "dialog-warning-symbolic"
            tooltip_text = "Configuration Required"
        else:
            row.set_subtitle(f"{subtitle} (Optional)")
            # No icon for optional/incomplete

        # Remove the previous icon widget if it exists
        if config["icon_widget"]:
            try:
                 row.remove(config["icon_widget"])
            except Exception as e:
                 # This can sometimes happen if the widget is already removed or parented elsewhere
                 print(f"Warning: Failed to remove previous icon for row '{key}': {e}")
            config["icon_widget"] = None
        
        # Add the new icon if one is needed
        if icon_name:
            # print(f"Adding icon '{icon_name}' to row '{key}'") # Diagnostic print
            new_icon_widget = Gtk.Image.new_from_icon_name(icon_name)
            if tooltip_text:
                 new_icon_widget.set_tooltip_text(tooltip_text) # Add tooltip for debugging
            row.add_suffix(new_icon_widget)
            config["icon_widget"] = new_icon_widget