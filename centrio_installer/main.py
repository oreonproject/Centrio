#!/usr/bin/env python3

# centrio_installer/main.py

import sys
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw

# Import the main window and constants
from .window import CentrioInstallerWindow
from .constants import APP_ID

class CentrioInstallerApp(Adw.Application):
    """The main GTK application class."""
    def __init__(self, **kwargs):
        super().__init__(application_id=APP_ID, **kwargs)
        self.connect('activate', self.on_activate)
        self.win = None

    def on_activate(self, app):
        """Called when the application is activated."""
        if not self.win:
             # Create the main window
             self.win = CentrioInstallerWindow(application=app)
        self.win.present()

    def do_shutdown(self):
        """Called when the application is shutting down."""
        # Ensure progress simulation timer is stopped if window exists
        if self.win and hasattr(self.win, 'progress_page') and hasattr(self.win.progress_page, 'stop_simulation'):
            print("Stopping progress simulation on shutdown...")
            self.win.progress_page.stop_simulation()
        # Call parent shutdown method
        Adw.Application.do_shutdown(self)

def main():
    """Main function to initialize and run the application."""
    Adw.init() # Initialize Adwaita
    app = CentrioInstallerApp()
    return app.run(sys.argv)

if __name__ == '__main__':
    # Ensure the application exits with the correct status code
    sys.exit(main()) 