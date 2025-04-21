# centrio_installer/pages/disk.py

import gi
import subprocess # For running lsblk
import json       # For parsing lsblk output
import shlex      # For safe command string generation
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from .base import BaseConfigurationPage
# D-Bus imports are no longer needed here
# from ..utils import dasbus, DBusError, dbus_available 
# from ..constants import (...) 

# Helper function to format size
def format_bytes(size_bytes):
    if size_bytes is None:
        return "N/A"
    # Simple GB conversion for display
    gb = size_bytes / (1024**3)
    if gb < 0.1:
        mb = size_bytes / (1024**2)
        return f"{mb:.1f} MiB"
    return f"{gb:.1f} GiB"

# --- Functions to Generate Partitioning Commands --- 

def generate_wipefs_command(disk_path):
    """Generates the wipefs command for a disk."""
    return ["wipefs", "-a", disk_path]

def generate_gpt_commands(disk_path, efi_size_mb=512):
    """Generates parted commands for a basic GPT layout (EFI + Root)."""
    commands = []
    # Ensure disk path is provided
    if not disk_path:
        print("ERROR: generate_gpt_commands called without disk_path")
        return []

    # Define partition start and end points
    efi_start = "1MiB"
    efi_end = f"{efi_size_mb + 1}MiB" # Add 1 MiB buffer from start
    root_start = efi_end
    root_end = "100%" # Use remaining space
    
    # Make GPT table
    commands.append(["parted", "-s", disk_path, "mklabel", "gpt"])
    # Make EFI partition
    commands.append(["parted", "-s", disk_path, "mkpart", "\"EFI System Partition\"", "fat32", efi_start, efi_end])
    # Set flags on EFI partition (part# 1)
    commands.append(["parted", "-s", disk_path, "set", "1", "boot", "on"])
    commands.append(["parted", "-s", disk_path, "set", "1", "esp", "on"])
    # Make root partition
    commands.append(["parted", "-s", disk_path, "mkpart", "\"Linux filesystem\"", "ext4", root_start, root_end])
    
    return commands

def generate_mkfs_commands(disk_path, partition_prefix=""):
    """Generates mkfs commands for the partitions created by generate_gpt_commands.
    Assumes standard partition naming (e.g., /dev/sda1, /dev/sda2).
    partition_prefix is used for devices like nvme (e.g., 'p').
    """
    commands = []
    # Determine partition device names
    # Handle drive letters vs nvme style
    if "nvme" in disk_path:
        part1 = f"{disk_path}{partition_prefix}1"
        part2 = f"{disk_path}{partition_prefix}2"
    else:
        part1 = f"{disk_path}1"
        part2 = f"{disk_path}2"

    # Format EFI partition (part# 1)
    commands.append(["mkfs.vfat", "-F32", part1])
    # Format root partition (part# 2)
    commands.append(["mkfs.ext4", "-F", part2]) # -F forces overwrite
    
    return commands

class DiskPage(BaseConfigurationPage):
    def __init__(self, main_window, overlay_widget, **kwargs):
        super().__init__(title="Installation Destination", subtitle="Select disks and configure partitioning", main_window=main_window, overlay_widget=overlay_widget, **kwargs)
        
        # State variables
        self.detected_disks = [] # List of dicts {name, path, size, model}
        self.selected_disks = set() # Set of disk paths (e.g., /dev/sda)
        self.scan_completed = False
        self.partitioning_method = None # "AUTOMATIC" or "MANUAL" or None
        self.disk_widgets = {} # Map path to row/check widgets
        
        # --- Add Initial Widgets --- 
        info_group = Adw.PreferencesGroup()
        self.add(info_group)
        info_label = Gtk.Label(label="Click \"Scan for Disks\" to detect storage devices.")
        info_label.set_margin_top(12)
        info_label.set_margin_bottom(12)
        info_label.set_wrap(True) 
        info_group.add(info_label)
        
        scan_button_group = Adw.PreferencesGroup()
        self.add(scan_button_group)
        self.scan_button = Gtk.Button(label="Scan for Disks") # Store ref
        self.scan_button.set_halign(Gtk.Align.CENTER)
        self.scan_button.connect("clicked", self.scan_for_disks)
        scan_button_group.add(self.scan_button)

        # --- Disk List (Initially Hidden) ---
        self.disk_list_group = Adw.PreferencesGroup(title="Detected Disks")
        self.disk_list_group.set_description("Select the disk(s) for installation.")
        self.disk_list_group.set_visible(False) # Hide until scan is complete
        self.add(self.disk_list_group)
        # We will add a ListBox here during scan completion
        self.disk_list_box = Gtk.ListBox()
        self.disk_list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.disk_list_box.set_visible(False) # Also hide list box initially
        self.disk_list_group.add(self.disk_list_box)

        # --- Partitioning Options (Initially Hidden) ---
        self.part_group = Adw.PreferencesGroup(title="Storage Configuration")
        self.part_group.set_description("Choose a partitioning method.")
        self.part_group.set_visible(False) # Hide until scan is complete
        self.add(self.part_group)
        
        # Radio buttons for partitioning method
        self.auto_part_check = Gtk.CheckButton(label="Automatic Partitioning")
        self.auto_part_check.set_tooltip_text("Use selected disk(s) with a default layout")
        self.manual_part_check = Gtk.CheckButton(label="Manual Partitioning", group=self.auto_part_check)
        self.manual_part_check.set_sensitive(False) # Disable manual for now
        
        self.auto_part_check.connect("toggled", self.on_partitioning_method_toggled)
        # manual_part_check.connect("toggled", self.on_partitioning_method_toggled)
        
        part_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        part_box.append(self.auto_part_check)
        part_box.append(self.manual_part_check)
        self.part_group.add(part_box)

        # --- Confirmation Button --- 
        button_group = Adw.PreferencesGroup()
        self.add(button_group)
        # Label reflects confirming the plan
        self.complete_button = Gtk.Button(label="Confirm Storage Plan") 
        self.complete_button.set_halign(Gtk.Align.CENTER)
        self.complete_button.set_margin_top(24)
        self.complete_button.add_css_class("suggested-action")
        self.complete_button.connect("clicked", self.apply_settings_and_return) 
        self.complete_button.set_sensitive(False) # Enable after scan, disk selection, and method choice
        button_group.add(self.complete_button)

        # No _connect_dbus needed anymore
        # self._connect_dbus() 
            
    def connect_and_fetch_data(self):
         # Data is fetched by scan_for_disks
         pass 

    def scan_for_disks(self, button):
        """Runs lsblk to find disks and updates the UI."""
        print("Scanning for disks using lsblk...")
        button.set_sensitive(False) 
        self.show_toast("Scanning for storage devices...")
        self.scan_completed = False
        self.partitioning_method = None
        self.selected_disks = set()
        self.disk_widgets = {}
        # Clear previous list items
        while child := self.disk_list_box.get_row_at_index(0):
             self.disk_list_box.remove(child)
             
        self.disk_list_group.set_visible(False)
        self.disk_list_box.set_visible(False)
        self.part_group.set_visible(False)
        self.complete_button.set_sensitive(False)
        self.auto_part_check.set_active(False)
        self.manual_part_check.set_active(False)

        try:
            # Run lsblk, request JSON output (-J), sizes in bytes (-b), specific columns
            cmd = ["lsblk", "-J", "-b", "-o", "NAME,SIZE,MODEL,TYPE,PATH"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
            lsblk_data = json.loads(result.stdout)
            
            self.detected_disks = []
            if "blockdevices" in lsblk_data:
                for device in lsblk_data["blockdevices"]:
                    # Filter for devices of type 'disk' (ignore partitions, lvm, etc.)
                    # Also ignore cd/dvd drives (usually model contains CD/DVD)
                    if device.get("type") == "disk" and not any(s in (device.get("model") or "").upper() for s in ["CD", "DVD"]):
                        disk_info = {
                            "name": device.get("name", "N/A"),
                            "path": device.get("path", "/dev/" + device.get("name", "")), # Construct path if missing
                            "size": device.get("size"), # Keep as int (bytes) or None
                            "model": device.get("model", "Unknown Model").strip()
                        }
                        self.detected_disks.append(disk_info)
            
            print(f"Detected disks: {self.detected_disks}")
            self.update_disk_list_ui()
            self.scan_completed = True
            self.show_toast(f"Scan complete. Found {len(self.detected_disks)} disk(s).")
            # Show groups now that scan is done
            if self.detected_disks:
                self.disk_list_group.set_visible(True)
                self.disk_list_box.set_visible(True)
                self.part_group.set_visible(True)
            else:
                 self.show_toast("No suitable disks found for installation.")
                 # Maybe show an error message in the group?

        except FileNotFoundError:
            print("ERROR: lsblk command not found.")
            self.show_toast("Error: lsblk command not found. Cannot scan disks.")
        except subprocess.CalledProcessError as e:
            print(f"ERROR: lsblk failed: {e}")
            print(f"Stderr: {e.stderr}")
            self.show_toast(f"Error running lsblk: {e.stderr}")
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse lsblk JSON output: {e}")
            self.show_toast("Error parsing disk information.")
        except subprocess.TimeoutExpired:
            print("ERROR: lsblk command timed out.")
            self.show_toast("Disk scan timed out.")
        except Exception as e:
            print(f"ERROR: Unexpected error during disk scan: {e}")
            self.show_toast(f"An unexpected error occurred during disk scan.")
        finally:
            # Re-enable scan button regardless of outcome
            button.set_sensitive(True)
            # Update confirmation button state based on scan results
            self.update_complete_button_state()
            
    def update_disk_list_ui(self):
        """Populates the disk list UI based on self.detected_disks."""
        # Clear previous items (redundant check, but safe)
        while child := self.disk_list_box.get_row_at_index(0):
             self.disk_list_box.remove(child)
        self.disk_widgets = {}

        if not self.detected_disks:
            # Display a message if no disks found
            row = Adw.ActionRow(title="No suitable disks found", subtitle="Cannot proceed with installation.")
            row.set_activatable(False)
            self.disk_list_box.append(row)
            return

        for disk in self.detected_disks:
            disk_path = disk["path"]
            disk_size_str = format_bytes(disk["size"])
            title = f"{disk_path} - {disk['model']}"
            subtitle = f"Size: {disk_size_str}"
            
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            check.connect("toggled", self.on_disk_toggled, disk_path)
            row.add_suffix(check)
            row.set_activatable_widget(check)
            self.disk_list_box.append(row)
            self.disk_widgets[disk_path] = {"row": row, "check": check}
            
    def on_disk_toggled(self, check_button, disk_path):
        """Handle checkbox toggle for disk selection."""
        if check_button.get_active():
            self.selected_disks.add(disk_path)
            print(f"Disk selected: {disk_path}")
        else:
            self.selected_disks.discard(disk_path)
            print(f"Disk deselected: {disk_path}")
        self.update_complete_button_state()

    def on_partitioning_method_toggled(self, button):
         """Handle radio button selection for partitioning method."""
         if self.auto_part_check.get_active():
             print("Partitioning method: AUTOMATIC")
             self.partitioning_method = "AUTOMATIC"
         elif self.manual_part_check.get_active():
             print("Partitioning method: MANUAL")
             self.partitioning_method = "MANUAL"
         else:
             # Should not happen with radio buttons unless both are inactive initially
             self.partitioning_method = None
             
         self.update_complete_button_state()

    def update_complete_button_state(self):
        """Enable the confirmation button only if conditions are met."""
        can_proceed = (
            self.scan_completed and 
            len(self.selected_disks) > 0 and 
            self.partitioning_method is not None
        )
        self.complete_button.set_sensitive(can_proceed)
        
    def apply_settings_and_return(self, button):
        """Confirms storage plan, generates commands, stores config, and returns to summary."""
        # Re-validate conditions before proceeding
        self.update_complete_button_state()
        if not self.complete_button.get_sensitive():
             # This provides more specific feedback than just not proceeding
             if not self.scan_completed:
                 self.show_toast("Please scan for disks first.")
             elif len(self.selected_disks) == 0:
                 self.show_toast("Please select at least one disk.")
             elif self.partitioning_method is None:
                 self.show_toast("Please select a partitioning method.")
             else:
                 self.show_toast("Cannot confirm storage plan. Please check selections.") # Generic fallback
             return

        print(f"--- Confirming Storage Plan ---")
        print(f"  Selected Disks: {list(self.selected_disks)}")
        print(f"  Partitioning Method: {self.partitioning_method}")
        
        # Initialize config with basic info
        config_values = {
            "method": self.partitioning_method,
            "target_disks": sorted(list(self.selected_disks)), 
            "commands": [] # Store generated commands here
        }

        if self.partitioning_method == "AUTOMATIC":
            primary_disk = sorted(list(self.selected_disks))[0]
            print(f"  Generating AUTOMATIC partitioning commands for: {primary_disk}")
            
            # Generate the command lists
            # Need to determine prefix for mkfs (e.g., 'p' for nvme)
            partition_prefix = "p" if "nvme" in primary_disk else ""
            
            wipe_cmd = generate_wipefs_command(primary_disk)
            parted_cmds = generate_gpt_commands(primary_disk)
            mkfs_cmds = generate_mkfs_commands(primary_disk, partition_prefix)
            
            all_commands = [wipe_cmd] + parted_cmds + mkfs_cmds
            
            # Add commands to the config_values
            # Storing as list of lists for clarity
            config_values["commands"] = all_commands 
            
            # Optionally, add details about the created partitions/mounts
            # This assumes the layout from generate_gpt_commands
            part1_suffix = f"{partition_prefix}1"
            part2_suffix = f"{partition_prefix}2"
            config_values["partitions"] = [
                {"device": f"{primary_disk}{part1_suffix}", "mountpoint": "/boot/efi", "fstype": "vfat"},
                {"device": f"{primary_disk}{part2_suffix}", "mountpoint": "/", "fstype": "ext4"}
            ]
            
            print(f"  Generated {len(all_commands)} commands for automatic partitioning.")
            # Example: print the first command
            if all_commands:
                 print(f"    Example command: {' '.join(shlex.quote(c) for c in all_commands[0])}")
                 
        elif self.partitioning_method == "MANUAL":
            # Manual partitioning commands would be generated here if implemented
            print("  Manual Plan: (Not implemented - no commands generated)")
            config_values["commands"] = []
            config_values["partitions"] = []

        # Show confirmation toast - COMMENTED OUT
        # if self.partitioning_method == \"AUTOMATIC\":
        #     self.show_toast(f\"Storage plan confirmed (Automatic). Commands generated.\")
        # elif self.partitioning_method == \"MANUAL\":
        #      if config_values[\"partitions\"]:
        #           self.show_toast(f\"Storage plan confirmed (Manual). Found partitions to use.\")
        #      else:
        #           # Should have returned earlier if no partitions found
        #           self.show_toast(\"Storage plan confirmed (Manual), but partition detection failed.\")
        # else:
        #      # Fallback for potentially other methods if added later
        #      self.show_toast(f\"Storage plan confirmed ({self.partitioning_method}).\")
            
        print("Storage plan confirmed. Returning to summary.") # Keep terminal log
        super().mark_complete_and_return(button, config_values=config_values)
        
        # --- TODO: Implement actual partitioning logic here --- 
        # This would involve: 
        # 1. Warning the user about data loss.
        # 2. Based on self.partitioning_method:
        #    - AUTOMATIC: Define a default partition scheme (e.g., /boot/efi, /, swap?)
        #                 Calculate sizes based on selected disk(s).
        #                 Call parted/mkfs/lvm/etc. to create partitions/filesystems.
        #    - MANUAL: Launch a separate partitioning tool UI (like GParted integrated) or 
        #              provide a detailed manual setup interface (very complex).
        # 3. Mount the created filesystems under a target directory (e.g., /mnt/sysimage).
        
        if self.partitioning_method == "AUTOMATIC":
            self.show_toast(f"Automatic partitioning on {', '.join(sorted(list(self.selected_disks)))} requested." )
            # Simulate success for now
            config_values = {
                "selected_disks": sorted(list(self.selected_disks)),
                "partitioning_method": self.partitioning_method,
                # Add other relevant details like mount points later
            }
            super().mark_complete_and_return(button, config_values=config_values)
            
        elif self.partitioning_method == "MANUAL":
            self.show_toast("Manual partitioning is not yet implemented.")
            # Do not mark complete if the selected method isn't implemented
        else:
             self.show_toast("Unknown partitioning method selected.") 