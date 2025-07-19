# centrio_installer/ui/welcome.py

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

# Import the utility function
from utils import get_os_release_info

class WelcomePage(Gtk.Box):
    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, **kwargs)
        
        # Get OS Name for branding
        os_info = get_os_release_info()
        distro_name = os_info.get("NAME", "Oreon")
        
        # Set smaller margins for better screen fit
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        
        # Create more compact content
        main_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_content.set_halign(Gtk.Align.CENTER)
        main_content.set_valign(Gtk.Align.CENTER)
        main_content.set_size_request(450, -1)
        
        # Package icon (changed to proper package box icon)
        icon = Gtk.Image.new_from_icon_name("system-software-install-symbolic")
        icon.set_pixel_size(96)  # Smaller icon
        icon.add_css_class("dim-label")
        main_content.append(icon)
        
        # Title
        title = Gtk.Label(label=f"Welcome to {distro_name}")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.CENTER)
        main_content.append(title)
        
        # Description
        description = Gtk.Label(label="Set up your new operating system in a few simple steps.")
        description.add_css_class("title-4")
        description.add_css_class("dim-label")
        description.set_halign(Gtk.Align.CENTER)
        description.set_wrap(True)
        main_content.append(description)
        
        # Language selection - more compact
        lang_group = Adw.PreferencesGroup(title="Language")
        
        self.lang_row = Adw.ComboRow(title="Installer Language")
        
        # Shorter language list for compactness
        lang_model = Gtk.StringList()
        languages = [
            "English (US)",
            "Español", 
            "Français",
            "Deutsch",
            "Italiano",
            "Português"
        ]
        
        for lang in languages:
            lang_model.append(lang)
        
        self.lang_row.set_model(lang_model)
        self.lang_row.set_selected(0)
        self.lang_row.connect("notify::selected", self.on_language_changed)
        
        lang_group.add(self.lang_row)
        main_content.append(lang_group)
        
        # Compact system info
        system_group = Adw.PreferencesGroup(title="Installation Overview")
        
        # OS version info
        version = os_info.get("VERSION", "10")
        version_row = Adw.ActionRow(
            title="Operating System",
            subtitle=f"{distro_name} {version}"
        )
        version_icon = Gtk.Image.new_from_icon_name("computer-symbolic")
        version_row.add_prefix(version_icon)
        system_group.add(version_row)
        
        # Installation type info
        install_row = Adw.ActionRow(
            title="Installation Type",
            subtitle="Full desktop with applications"
        )
        install_icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        install_row.add_prefix(install_icon)
        system_group.add(install_row)
        
        # Estimated time
        time_row = Adw.ActionRow(
            title="Estimated Time",
            subtitle="15-30 minutes"
        )
        time_icon = Gtk.Image.new_from_icon_name("alarm-symbolic")
        time_row.add_prefix(time_icon)
        system_group.add(time_row)
        
        main_content.append(system_group)
        
        # Compact features highlight
        features_group = Adw.PreferencesGroup(title="What's Included")
        
        features = [
            ("applications-system-symbolic", "Desktop Environment", "Modern GNOME desktop"),
            ("network-wireless-symbolic", "Network Support", "Wi-Fi and wired connectivity"),
            ("application-x-addon-symbolic", "Software Store", "Flatpak applications"),
            ("security-high-symbolic", "Security", "Firewall and updates")
        ]
        
        for icon_name, title_text, description_text in features:
            feature_row = Adw.ActionRow(title=title_text, subtitle=description_text)
            feature_icon = Gtk.Image.new_from_icon_name(icon_name)
            feature_row.add_prefix(feature_icon)
            features_group.add(feature_row)
        
        main_content.append(features_group)
        
        # Footer
        footer_label = Gtk.Label(
            label="Click Next to begin configuration.",
            justify=Gtk.Justification.CENTER
        )
        footer_label.add_css_class("dim-label")
        footer_label.set_wrap(True)
        main_content.append(footer_label)
        
        # Add the main content to this box
        self.append(main_content)

    def on_language_changed(self, combo_row, pspec):
        """Handle language selection change."""
        selected = combo_row.get_selected()
        languages = ["en_US", "es_ES", "fr_FR", "de_DE", "it_IT", "pt_BR"]
        
        if selected < len(languages):
            lang_code = languages[selected]
            print(f"Language selected: {lang_code}")
        else:
            print("Invalid language selection") 