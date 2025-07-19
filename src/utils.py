# centrio_installer/utils.py
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio # Added Gio for file operations

import os
import re
import subprocess

# Attempt D-Bus import
try:
    # Use dasbus
    import dasbus.connection
    from dasbus.error import DBusError
    dbus_available = True
except ImportError:
    dasbus = None 
    DBusError = Exception # Placeholder
    dbus_available = False
    print("WARNING: dasbus library not found. D-Bus communication will be disabled.")

# --- Timezone Helpers (Simulated from pyanaconda.timezone) ---
# In a real integration, import these from pyanaconda.timezone
# For now, provide dummy implementations
try:
    import pytz
    pytz_available = True
except ImportError:
    pytz = None
    pytz_available = False
    print("WARNING: pytz not found. Timezone list will be minimal.")

def ana_get_all_regions_and_timezones():
    """Placeholder for pyanaconda.timezone.get_all_regions_and_timezones."""
    if pytz_available:
        # Basic simulation using pytz common timezones
        try:
            return sorted(pytz.common_timezones)
        except Exception as e:
             print(f"Error getting pytz timezones: {e}")
             return ["UTC", "GMT"]
    else:
        # Minimal fallback
        return ["UTC", "GMT", "America/New_York", "Europe/London", "Asia/Tokyo"]

def ana_get_keyboard_layouts():
    """Fetches available console keyboard layouts using localectl."""
    print("Fetching keyboard layouts using localectl...")
    try:
        # Get console keymaps
        result = subprocess.run(["localectl", "list-keymaps"], 
                                capture_output=True, text=True, check=True)
        keymaps = sorted([line for line in result.stdout.split('\n') if line])
        print(f"  Found {len(keymaps)} console keymaps.")
        
        # TODO: Also fetch X11 layouts/variants/options if needed for a more detailed UI
        # result_x11 = subprocess.run(["localectl", "list-x11-keymap-layouts"], ...)
        
        # Return console keymaps for now for simplicity
        return keymaps if keymaps else ["us"] # Fallback
    except FileNotFoundError:
        print("ERROR: localectl command not found. Using fallback layouts.")
        return ["us", "gb", "de", "fr"] # Fallback list
    except subprocess.CalledProcessError as e:
        print(f"ERROR: localectl list-keymaps failed: {e}. Using fallback layouts.")
        return ["us", "gb", "de", "fr"]
    except Exception as e:
        print(f"ERROR: Unexpected error fetching keymaps: {e}. Using fallback layouts.")
        return ["us", "gb", "de", "fr"]

def ana_get_available_locales():
    """Fetches available locales using localectl."""
    print("Fetching available locales using localectl...")
    locales = {}
    try:
        result = subprocess.run(["localectl", "list-locales"], 
                                capture_output=True, text=True, check=True)
        raw_locales = [line.strip() for line in result.stdout.split('\n') if line and '.' in line]
        # Attempt to generate a display name (basic)
        for locale_code in raw_locales:
             # Simple conversion for display: en_US.UTF-8 -> English (US) UTF-8
             parts = locale_code.split('.')[0].split('_')
             lang = parts[0]
             country = f"({parts[1]})" if len(parts) > 1 else ""
             # This name generation is very basic, ideally use a locale library
             display_name = f"{lang.capitalize()} {country}".strip()
             # Use code as key, display name as value (or vice-versa if needed by UI)
             locales[locale_code] = display_name 
             
        print(f"  Found {len(locales)} locales.")
        # Sort by display name for UI
        sorted_locales = dict(sorted(locales.items(), key=lambda item: item[1]))
        return sorted_locales if sorted_locales else {"en_US.UTF-8": "English (US)"} # Fallback
        
    except FileNotFoundError:
        print("ERROR: localectl command not found. Using fallback locales.")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: localectl list-locales failed: {e}. Using fallback locales.")
    except Exception as e:
        print(f"ERROR: Unexpected error fetching locales: {e}. Using fallback locales.")
        
    # Fallback list if errors occurred
    return {
        "en_US.UTF-8": "English (US)",
        "es_ES.UTF-8": "Spanish (Spain)",
        "fr_FR.UTF-8": "French (France)",
        "de_DE.UTF-8": "German (Germany)"
    } 

from constants import APP_ID

def get_os_release_info(target_root=None):
    """Parses /etc/os-release (or /usr/lib/os-release) to get NAME and VERSION_ID.
    If target_root is provided, reads from within that root.
    """
    info = {"NAME": "Linux", "VERSION_ID": None, "ID": None} # Defaults
    release_file_path = None
    base_path = target_root if target_root else "/"
    
    # Check standard locations relative to base_path
    etc_path = os.path.join(base_path, "etc/os-release")
    usr_lib_path = os.path.join(base_path, "usr/lib/os-release")
    
    if os.path.exists(etc_path):
        release_file_path = etc_path
    elif os.path.exists(usr_lib_path):
        release_file_path = usr_lib_path
    
    if release_file_path:
        try:
            with open(release_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        # Remove quotes from value if present
                        value = value.strip('"\'') 
                        # Store common keys
                        if key in ["NAME", "VERSION_ID", "ID"]:
                            info[key] = value
        except Exception as e:
            print(f"Warning: Failed to parse {release_file_path}: {e}")
            
    return info

# Function to get Anaconda bus address (Modified)
def get_anaconda_bus_address():
    # This function likely contained D-Bus logic to find the Anaconda bus.
    # As D-Bus is removed/optional, provide a placeholder.
    print("Warning: get_anaconda_bus_address() is not implemented (D-Bus disabled/removed).")
    pass # Add pass to make the function definition valid
    # // ... existing code ... # This comment is likely outdated now

# Constants
# ANACONDA_BUS_NAME = "org.fedoraproject.Anaconda.Boss"
# ANACONDA_OBJECT_PATH = "/org/fedoraproject/Anaconda/Boss" 