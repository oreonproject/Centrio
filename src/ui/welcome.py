# centrio_installer/ui/welcome.py

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

# Import the utility function
from utils import get_os_release_info

# Simple translation dictionary for installer interface
TRANSLATIONS = {
    'en_US': {
        'welcome': 'Welcome to {}',
        'description': 'Set up your new operating system in a few simple steps.',
        'language': 'Language',
        'installer_language': 'Installer Language',
        'installation_overview': 'Installation Overview',
        'operating_system': 'Operating System',
        'installation_type': 'Installation Type',
        'full_desktop': 'Full desktop with applications',
        'estimated_time': 'Estimated Time',
        'time_estimate': '15-30 minutes',
        'click_next': 'Click Next to begin configuration.',
        'language_selected': 'Language Selected',
        'language_applied': 'Language set to {}. This will be applied to the installed system.'
    },
    'es_ES': {
        'welcome': 'Bienvenido a {}',
        'description': 'Configure su nuevo sistema operativo en unos pocos pasos simples.',
        'language': 'Idioma',
        'installer_language': 'Idioma del Instalador',
        'installation_overview': 'Resumen de la Instalación',
        'operating_system': 'Sistema Operativo',
        'installation_type': 'Tipo de Instalación',
        'full_desktop': 'Escritorio completo con aplicaciones',
        'estimated_time': 'Tiempo Estimado',
        'time_estimate': '15-30 minutos',
        'click_next': 'Haga clic en Siguiente para comenzar la configuración.',
        'language_selected': 'Idioma Seleccionado',
        'language_applied': 'Idioma establecido en {}. Esto se aplicará al sistema instalado.'
    },
    'fr_FR': {
        'welcome': 'Bienvenue sur {}',
        'description': 'Configurez votre nouveau système d\'exploitation en quelques étapes simples.',
        'language': 'Langue',
        'installer_language': 'Langue de l\'Installateur',
        'installation_overview': 'Aperçu de l\'Installation',
        'operating_system': 'Système d\'Exploitation',
        'installation_type': 'Type d\'Installation',
        'full_desktop': 'Bureau complet avec applications',
        'estimated_time': 'Temps Estimé',
        'time_estimate': '15-30 minutes',
        'click_next': 'Cliquez sur Suivant pour commencer la configuration.',
        'language_selected': 'Langue Sélectionnée',
        'language_applied': 'Langue définie sur {}. Cela sera appliqué au système installé.'
    }
}

def get_text(key, lang_code='en_US', *args):
    """Get translated text for the given key and language."""
    if lang_code in TRANSLATIONS and key in TRANSLATIONS[lang_code]:
        text = TRANSLATIONS[lang_code][key]
        return text.format(*args) if args else text
    else:
        # Fallback to English
        if key in TRANSLATIONS['en_US']:
            text = TRANSLATIONS['en_US'][key]
            return text.format(*args) if args else text
        return key

class WelcomePage(Gtk.Box):
    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, **kwargs)
        
        # Initialize language
        self.selected_language = 'en_US'
        
        # Get OS Name for branding
        os_info = get_os_release_info()
        distro_name = os_info.get("NAME", "Oreon")
        
        # Set smaller margins for better screen fit
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.set_margin_top(18)
        self.set_margin_bottom(18)
        self.set_margin_start(18)
        self.set_margin_end(18)
        
        # Create more compact content
        main_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_content.set_halign(Gtk.Align.CENTER)
        main_content.set_valign(Gtk.Align.CENTER)
        main_content.set_size_request(450, -1)
        
        # Package icon (changed to proper package box icon)
        icon = Gtk.Image.new_from_icon_name("system-software-install-symbolic")
        icon.set_pixel_size(72)  # Even smaller icon
        icon.add_css_class("dim-label")
        main_content.append(icon)
        
        # Title
        title = Gtk.Label(label=get_text("welcome", self.selected_language, distro_name))
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.CENTER)
        main_content.append(title)
        
        # Description
        description = Gtk.Label(label=get_text("description", self.selected_language))
        description.add_css_class("title-4")
        description.add_css_class("dim-label")
        description.set_halign(Gtk.Align.CENTER)
        description.set_wrap(True)
        main_content.append(description)
        
        # Language selection - more compact
        lang_group = Adw.PreferencesGroup(title=get_text("language"))
        
        self.lang_row = Adw.ComboRow(title=get_text("installer_language"))
        
        # Comprehensive language list with proper codes
        lang_model = Gtk.StringList()
        languages = [
            ("English (US)", "en_US"),
            ("English (UK)", "en_GB"),
            ("Español", "es_ES"),
            ("Français", "fr_FR"),
            ("Deutsch", "de_DE"),
            ("Italiano", "it_IT"),
            ("Português (Brasil)", "pt_BR"),
            ("Português (Portugal)", "pt_PT"),
            ("Русский", "ru_RU"),
            ("中文 (简体)", "zh_CN"),
            ("中文 (繁體)", "zh_TW"),
            ("日本語", "ja_JP"),
            ("한국어", "ko_KR"),
            ("العربية", "ar_SA"),
            ("हिन्दी", "hi_IN"),
            ("ไทย", "th_TH"),
            ("Türkçe", "tr_TR"),
            ("Polski", "pl_PL"),
            ("Nederlands", "nl_NL"),
            ("Svenska", "sv_SE"),
            ("Norsk", "no_NO"),
            ("Dansk", "da_DK"),
            ("Suomi", "fi_FI"),
            ("Čeština", "cs_CZ"),
            ("Slovenčina", "sk_SK"),
            ("Magyar", "hu_HU"),
            ("Română", "ro_RO"),
            ("Български", "bg_BG"),
            ("Hrvatski", "hr_HR"),
            ("Slovenščina", "sl_SI"),
            ("Eesti", "et_EE"),
            ("Latviešu", "lv_LV"),
            ("Lietuvių", "lt_LT"),
            ("Ελληνικά", "el_GR"),
            ("Català", "ca_ES"),
            ("Galego", "gl_ES"),
            ("Euskara", "eu_ES"),
            ("Gaeilge", "ga_IE"),
            ("Cymraeg", "cy_GB")
        ]
        
        self.language_codes = [code for _, code in languages]
        
        for name, _ in languages:
            lang_model.append(name)
        
        self.lang_row.set_model(lang_model)
        
        # Try to detect current system language
        current_lang = self._detect_current_language()
        if current_lang in self.language_codes:
            try:
                idx = self.language_codes.index(current_lang)
                self.lang_row.set_selected(idx)
            except ValueError:
                self.lang_row.set_selected(0)  # Default to English
        else:
            self.lang_row.set_selected(0)  # Default to English
            
        self.lang_row.connect("notify::selected", self.on_language_changed)
        
        lang_group.add(self.lang_row)
        main_content.append(lang_group)
        
        # Compact system info
        system_group = Adw.PreferencesGroup(title=get_text("installation_overview"))
        
        # OS version info
        version = os_info.get("VERSION", "10")
        version_row = Adw.ActionRow(
            title=get_text("operating_system"),
            subtitle=f"{distro_name} {version}"
        )
        version_icon = Gtk.Image.new_from_icon_name("computer-symbolic")
        version_row.add_prefix(version_icon)
        system_group.add(version_row)
        
        # Installation type info
        install_row = Adw.ActionRow(
            title=get_text("installation_type"),
            subtitle=get_text("full_desktop")
        )
        install_icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        install_row.add_prefix(install_icon)
        system_group.add(install_row)
        
        # Estimated time
        time_row = Adw.ActionRow(
            title=get_text("estimated_time"),
            subtitle=get_text("time_estimate")
        )
        time_icon = Gtk.Image.new_from_icon_name("alarm-symbolic")
        time_row.add_prefix(time_icon)
        system_group.add(time_row)
        
        main_content.append(system_group)
        
        # Footer
        footer_label = Gtk.Label(
            label=get_text("click_next"),
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
        
        if selected >= 0 and selected < len(self.language_codes):
            lang_code = self.language_codes[selected]
            print(f"Language selected: {lang_code}")
            
            # Store the selected language for use during installation
            # Don't change system locale now - that happens after install
            self.selected_language = lang_code
            
            # Update the interface text
            self.update_interface_text()
            
            # Show a message that the language will be applied after installation
            dialog = Gtk.MessageDialog(
                transient_for=self.get_root(),
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=get_text("language_selected", self.selected_language),
                secondary_text=get_text("language_applied", self.selected_language, lang_code)
            )
            dialog.connect("response", lambda d, response: dialog.destroy())
            dialog.present()
        else:
            print("Invalid language selection")
    
    def update_interface_text(self):
        """Update the interface text based on the selected language."""
        # This would update all the text elements in the interface
        # For now, we'll just print that the language changed
        print(f"Interface language updated to: {self.selected_language}")
    
    def _detect_current_language(self):
        """Detect the current system language."""
        try:
            import subprocess
            import os
            
            # First try to get from environment
            lang = os.environ.get('LANG', '')
            if lang:
                # Extract language code (e.g., "en_US.UTF-8" -> "en_US")
                lang_code = lang.split('.')[0]
                return lang_code
            
            # Fallback to localectl
            result = subprocess.run(["localectl", "status"], 
                                  capture_output=True, text=True, check=True)
            output = result.stdout
            
            # Parse System Locale
            import re
            locale_match = re.search(r"System Locale: LANG=(\S+)", output)
            if locale_match:
                lang = locale_match.group(1)
                lang_code = lang.split('.')[0]
                return lang_code
                
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        
        # Default fallback
        return "en_US" 