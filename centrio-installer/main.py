#!/usr/bin/env python3

# centrio_installer/main.py

import sys
import gi
import logging # Import logging
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib

# Import the main window and constants
from .window import CentrioInstallerWindow
from .constants import APP_ID

# --- Setup Logging ---
log_format = '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
logging.basicConfig(level=logging.INFO, format=log_format)
# You could also log to a file:
# logging.basicConfig(filename='/tmp/centrio-installer.log', filemode='w', level=logging.DEBUG, format=log_format)

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
            logging.info("Stopping progress simulation on shutdown...") # Use logging
            self.win.progress_page.stop_simulation()
        # Call parent shutdown method
        Adw.Application.do_shutdown(self)

def main():
    """Main function to initialize and run the application."""
    try:
        logging.info("Centrio Installer starting...") # Log start
        Adw.init() # Initialize Adwaita
        app = CentrioInstallerApp()
        exit_status = app.run(sys.argv)
        logging.info(f"Centrio Installer finished with exit status: {exit_status}") # Log end
        return exit_status
    except Exception as e:
        # Log any unhandled exceptions before exiting
        logging.critical("Unhandled exception caused installer to crash!", exc_info=True)
        # Optionally, show a critical error dialog to the user if possible
        # (Might be hard if GTK itself crashed)
        return 1 # Return a non-zero exit code for error

if __name__ == '__main__':
    # Ensure the application exits with the correct status code
    sys.exit(main()) 