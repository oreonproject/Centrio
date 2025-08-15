#!/usr/bin/env python3
"""
Centrio Installer - Main entry point
"""

import sys
import os
import logging
import gettext
import locale
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
)

# Set up internationalization
def setup_i18n():
    """Set up internationalization support."""
    try:
        # Get the current locale
        current_locale = locale.getlocale()[0]
        if not current_locale:
            current_locale = 'en_US'
        
        # Set up gettext with absolute locale dir
        project_root = Path(__file__).resolve().parent.parent
        locale_dir = str(project_root / 'locale')
        gettext.install('centrio', localedir=locale_dir)
        
        # Try to set the locale
        try:
            locale.setlocale(locale.LC_ALL, current_locale)
        except locale.Error:
            # Fallback to default
            locale.setlocale(locale.LC_ALL, '')
            
        print(f"Internationalization set up for locale: {current_locale}")
        
    except Exception as e:
        print(f"Warning: Could not set up internationalization: {e}")

def main():
    """Main entry point for the Centrio installer."""
    # Set up internationalization first
    setup_i18n()
    
    # Import after i18n setup
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Adw
    from window import CentrioInstallerWindow
    
    # Create the application
    app = Adw.Application(
        application_id="org.centrio.installer",
        flags=0
    )
    
    def on_activate(app):
        """Handle application activation."""
        logging.info("Centrio Installer starting...")
        win = CentrioInstallerWindow(application=app)
        win.present()
    
    app.connect("activate", on_activate)
    
    # Run the application
    exit_status = app.run(sys.argv)
    return exit_status

if __name__ == "__main__":
    sys.exit(main()) 