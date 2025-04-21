# centrio_installer/pages/disk.py

import gi
import subprocess # For running lsblk
import json       # For parsing lsblk output
import shlex      # For safe command string generation
import os         # For path manipulation
import re # For parsing losetup
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

# --- Helper Functions to Check Host Usage ---

def get_host_mounts():
    """Gets currently mounted filesystems on the host."""
    mounts = {}
    try:
        # Use findmnt for reliable mount info, JSON output
        cmd = ["findmnt", "-J", "-o", "SOURCE,TARGET,FSTYPE,OPTIONS"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
        mount_data = json.loads(result.stdout)
        if "filesystems" in mount_data:
            for fs in mount_data["filesystems"]:
                source = fs.get("source")
                target = fs.get("target")
                if source and target:
                    # Store source device (e.g., /dev/sda1, /dev/mapper/vg-lv)
                    mounts[target] = source 
        print(f"Detected host mounts: {mounts}") # Log detected mounts
        return mounts
    except Exception as e:
        print(f"Warning: Failed to get host mounts using findmnt: {e}")
        return {}

def get_host_lvm_pvs():
    """Gets active LVM Physical Volumes on the host."""
    pvs = set()
    try:
        # Get PV names
        cmd = ["pvs", "--noheadings", "-o", "pv_name"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
        for line in result.stdout.splitlines():
            pv_name = line.strip()
            if pv_name:
                # Resolve device path if it's a symlink (e.g., /dev/dm-*)
                try:
                    real_path = os.path.realpath(pv_name)
                    pvs.add(real_path)
                except Exception:
                    pvs.add(pv_name) # Add original if realpath fails
        print(f"Detected host LVM PVs: {pvs}") # Log detected PVs
        return pvs
    except Exception as e:
        print(f"Warning: Failed to get host LVM PVs: {e}")
        return set()

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
            
    def find_physical_disk_for_path(self, target_path, block_devices):
        """Traces a given path back to its parent physical disk using lsblk data, handling loop devices."""
        print(f"--- Tracing physical disk for path: {target_path} ---")
        if not block_devices or not target_path:
            print("  Error: Missing block_devices or target_path.")
            return None

        # Create a mapping from any path to its device info and parent path (pkname)
        path_map = {}
        queue = list(block_devices)
        while queue:
            dev = queue.pop(0)
            dev_path = dev.get("path")
            if dev_path:
                path_map[dev_path] = {"info": dev, "pkname": dev.get("pkname")}
            if "children" in dev:
                queue.extend(dev["children"])

        # Trace upwards from the target_path
        current_path = target_path
        visited = set() # Prevent infinite loops

        while current_path and current_path not in visited:
            visited.add(current_path)
            print(f"  Tracing: current_path = {current_path}")

            # --- Handle Loop Device ---
            if current_path.startswith("/dev/loop"):
                print(f"  Path {current_path} is a loop device. Finding backing file...")
                try:
                    # Get Backing File path
                    cmd_losetup = ["losetup", "-O", "BACK-FILE", "--noheadings", current_path]
                    result_losetup = subprocess.run(cmd_losetup, capture_output=True, text=True, check=True, timeout=5)
                    backing_file = result_losetup.stdout.strip()
                    print(f"    Loop device {current_path} backing file: {backing_file}")

                    if backing_file and backing_file != "(deleted)": # Cannot trace deleted backing files reliably yet
                        backing_file_dir = os.path.dirname(backing_file)
                        print(f"    Finding mountpoint containing backing file directory: {backing_file_dir}...")

                        # Use findmnt to find the source device for the directory containing the backing file
                        # findmnt -n -o SOURCE --target /path/to/dir
                        cmd_findmnt_src = ["findmnt", "-n", "-o", "SOURCE", "--target", backing_file_dir]
                        result_findmnt_src = subprocess.run(cmd_findmnt_src, capture_output=True, text=True, check=True, timeout=5)
                        source_device = result_findmnt_src.stdout.strip()

                        if source_device:
                            print(f"    Backing file directory {backing_file_dir} is on source device: {source_device}")
                            current_path = source_device # Continue tracing from the source device
                            continue # Restart loop with the new source device path
                        else:
                            print(f"    ERROR: Could not find source device for backing file directory {backing_file_dir}")
                            # If findmnt fails, try the pkname fallback below
                            print(f"    Falling back to check pkname for loop device {current_path}...")
                            # pass # Let it fall through to pkname check

                    # Fallback for (deleted) or if findmnt failed for non-deleted
                    # --- Attempt to trace via the loop device's parent in lsblk ---
                    print(f"    Trying lsblk parent (pkname) for loop device {current_path}...")
                    if current_path in path_map:
                         parent_path = path_map[current_path]["pkname"]
                         if parent_path:
                              print(f"    Found lsblk parent (pkname): {parent_path}. Continuing trace from parent.")
                              current_path = parent_path
                              continue # Restart loop with the parent device path
                         else:
                              print(f"    ERROR: Loop device {current_path} has no pkname in lsblk.")
                              return None
                    else:
                         # Should not happen if map was built correctly
                         print(f"    ERROR: Loop device {current_path} not found in path_map for pkname lookup.")
                         return None
                    # --- End Fallback ---

                except subprocess.CalledProcessError as e:
                     print(f"  ERROR: Command failed while processing loop device {current_path}: {' '.join(e.cmd)}")
                     print(f"  Stderr: {e.stderr}")
                     print(f"  Continuing trace without resolving loop device further...") # Try to continue if command fails
                     # Let it fall through to the general path/pkname check below
                except Exception as e:
                    print(f"  ERROR: Failed to process loop device {current_path}: {e}")
                    return None # Critical error if something else goes wrong
            # --- End Handle Loop Device ---

            # --- Handle Device Mapper ---
            elif current_path.startswith("/dev/mapper/"):
                 print(f"  Path {current_path} is a device mapper device. Checking lsblk parent (pkname)...\")
                 parent_path = path_map.get(current_path, {}).get("pkname")

                 if parent_path:
                      print(f"    Found lsblk parent (pkname): {parent_path}. Continuing trace from parent.")
                      current_path = parent_path
                      continue # Restart loop with parent path
                 else:
                      print(f"    Warning: Device mapper path {current_path} has no pkname in lsblk. Trying dmsetup...")
                      try:
                           cmd_dmsetup = ["dmsetup", "deps", "-o", "devname", current_path]
                           result_dmsetup = subprocess.run(cmd_dmsetup, capture_output=True, text=True, check=True, timeout=5)
                           # Output format: " device_name (major:minor)\n ..."
                           # We want the first device_name
                           deps_output = result_dmsetup.stdout.strip()
                           match = re.search(r"^\s*(\S+)", deps_output) # Find first non-whitespace sequence
                           if match:
                                underlying_dev = match.group(1)
                                # Ensure it's a device path
                                if underlying_dev.startswith("/dev/"):
                                     print(f"    Found underlying device via dmsetup: {underlying_dev}. Continuing trace.")
                                     current_path = underlying_dev
                                     continue # Restart loop with the underlying device
                                else:
                                     print(f"    Warning: dmsetup output '{underlying_dev}' doesn't look like a device path.")
                           else:
                                print(f"    Warning: Could not parse underlying device from dmsetup output: {deps_output}")
                      except FileNotFoundError:
                           print(f"    ERROR: dmsetup command not found. Cannot resolve DM dependency for {current_path}.")
                           return None # Cannot proceed without dmsetup if pkname missing
                      except subprocess.CalledProcessError as e:
                           print(f"    ERROR: dmsetup failed for {current_path}: {e.stderr}")
                           # Proceed to general check below? Might fail.
                      except Exception as e:
                           print(f"    ERROR: Unexpected error running dmsetup for {current_path}: {e}")
                           # Proceed to general check below? Might fail.

                      print(f"    Falling back to general check for {current_path} after dmsetup attempt.")
                      # If dmsetup fails or doesn't find a usable path, proceed to general check below

            # --- General Path Check ---
            if current_path not in path_map:
                print(f"  Error: Path {current_path} not found in lsblk map (needed for type/pkname check).")
                # It might have been resolved via dmsetup/losetup to a path not originally scanned
                # If we can't find it now, we cannot determine if it's a 'disk' or find its parent.
                return None


            dev_info = path_map[current_path]["info"]
            dev_type = dev_info.get("type")

            if dev_type == "disk":
                print(f"  Found parent disk: {current_path}")
                return current_path

            parent_path = path_map[current_path]["pkname"]
            if not parent_path:
                 print(f"  Error: Path {current_path} (type: {dev_type}) has no parent (pkname).")
                 # If it's a disk but type wasn't exactly 'disk', maybe return anyway?
                 if dev_type and "disk" in dev_type.lower():
                      print(f"  Treating path {current_path} as disk based on type '{dev_type}'.")
                      return current_path
                 return None # Cannot trace further without parent

            current_path = parent_path

        if current_path in visited: print(f"  Error: Loop detected while tracing parent for {target_path}")
        else: print(f"  Error: Could not find parent disk for {target_path} (trace ended unexpectedly)")
        return None

    def scan_for_disks(self, button):
        """Runs lsblk once, identifies the live OS disk, checks usage, and updates the UI."""
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
            # Run lsblk ONCE, get JSON tree, include MOUNTPOINT
            cmd = ["lsblk", "-J", "-b", "-p", "-o", "NAME,PATH,SIZE,MODEL,TYPE,PKNAME,MOUNTPOINT"]
            print(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
            lsblk_data = json.loads(result.stdout)
            
            self.detected_disks = []
            all_block_devices = lsblk_data.get("blockdevices", [])
            live_os_disk_path = None

            # --- Find the physical disk hosting the live OS root ('/') ---
            print("--- Searching for live OS root mountpoint ('/') ---")
            root_source_path = None
            queue = list(all_block_devices)
            processed_for_root = set() # Avoid reprocessing children
            while queue:
                 dev = queue.pop(0)
                 dev_path = dev.get("path")
                 if not dev_path or dev_path in processed_for_root: continue
                 processed_for_root.add(dev_path)

                 # Check current device
                 if dev.get("mountpoint") == "/":
                      root_source_path = dev_path
                      print(f"  Found root mountpoint '/' on device: {root_source_path}")
                      break # Found it

                 # Check children
                 if "children" in dev:
                      for child in dev["children"]:
                            child_path = child.get("path")
                            if child_path and child.get("mountpoint") == "/":
                                 root_source_path = child_path
                                 print(f"  Found root mountpoint '/' on child device: {root_source_path}")
                                 break # Found it
                            # Add grandchildren only if root not found yet
                            if "children" in child and root_source_path is None:
                                 queue.extend(child["children"])
                 if root_source_path: break # Exit outer loop if found

            if root_source_path:
                 live_os_disk_path = self.find_physical_disk_for_path(root_source_path, all_block_devices)
                 if live_os_disk_path:
                      print(f"--- Identified Live OS physical disk: {live_os_disk_path} ---")
                 else:
                      print("--- WARNING: Could not trace root mountpoint source back to a physical disk! ---")
            else:
                 print("--- WARNING: Could not find root mountpoint '/' in lsblk output! ---")
            # --- Finished searching for live OS disk ---

            # --- Process all detected physical disks ---
            print("--- Processing detected disks ---")
            for device in all_block_devices:
                if device.get("type") == "disk" and not any(s in (device.get("model") or "").upper() for s in ["CD", "DVD"]):
                    disk_path = device.get("path")
                    if not disk_path: continue

                    # Mark disk as unusable only if it's the one hosting the live OS
                    is_live_os_disk = (disk_path == live_os_disk_path)
                    
                    print(f"  Processing disk: {disk_path}, Is Live OS Disk? {is_live_os_disk}")

                    disk_info = {
                        "name": device.get("name", "N/A"),
                        "path": disk_path,
                        "size": device.get("size"),
                        "model": device.get("model", "Unknown Model").strip(),
                        "is_live_os_disk": is_live_os_disk # Changed flag name
                    }
                    self.detected_disks.append(disk_info)

            print(f"Detected disks list: {self.detected_disks}")
            self.update_disk_list_ui()
            self.scan_completed = True
            self.show_toast(f"Scan complete. Found {len(self.detected_disks)} disk(s).")
            if self.detected_disks:
                self.disk_list_group.set_visible(True)
                self.disk_list_box.set_visible(True)
                self.part_group.set_visible(True)
            else:
                 self.show_toast("No suitable disks found for installation.")

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
            self.update_complete_button_state()
            
    def update_disk_list_ui(self):
        """Populates the disk list UI, marking the live OS disk as unusable."""
        # Clear previous items
        while child := self.disk_list_box.get_row_at_index(0):
             self.disk_list_box.remove(child)
        self.disk_widgets = {}

        if not self.detected_disks:
            # Display a message if no disks found
            row = Adw.ActionRow(title="No suitable disks found", subtitle="Cannot proceed with installation.")
            row.set_activatable(False)
            self.disk_list_box.append(row)
            return

        found_usable_disk = False
        for disk in self.detected_disks:
            disk_path = disk["path"]
            disk_size_str = format_bytes(disk["size"])
            title = f"{disk_path} - {disk['model']}"
            subtitle = f"Size: {disk_size_str}"
            
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            
            if disk["is_live_os_disk"]: 
                 print(f"!!! UI Update: Marking {disk['path']} (Live OS Disk) as insensitive.")
                 row.set_subtitle(subtitle + " (Live OS Disk - Cannot select)")
                 row.set_sensitive(False) 
                 check.set_sensitive(False)
            else:
                 found_usable_disk = True
                 check.connect("toggled", self.on_disk_toggled, disk_path)
                 row.add_suffix(check)
                 row.set_activatable_widget(check)

            self.disk_list_box.append(row)
            # Store widgets even if disabled, for completeness
            self.disk_widgets[disk_path] = {"row": row, "check": check} 
            
        if not found_usable_disk:
             # Optionally add a specific message if only host disks were found
             print("Warning: No usable disks detected (only Live OS disk found?).")
             # Consider adding a visible label to the UI group
             
    def on_disk_toggled(self, check_button, disk_path):
        print(f"--- Toggle event for {disk_path} ---")
        # Check sensitivity (which depends on is_live_os_disk flag)
        if disk_path in self.disk_widgets and self.disk_widgets[disk_path]["row"].get_sensitive():
            if check_button.get_active():
                print(f"  Adding {disk_path} to selected_disks.")
                self.selected_disks.add(disk_path)
            else:
                print(f"  Removing {disk_path} from selected_disks.")
                self.selected_disks.discard(disk_path)
        else:
             print(f"  ROW NOT SENSITIVE (likely Live OS disk). Forcing checkbox inactive for {disk_path}.")
             if check_button.get_active(): # Prevent state change if already inactive
                  GLib.idle_add(check_button.set_active, False)

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
        print(f"--- Updating button state ---")
        print(f"  Selected disks BEFORE validation: {self.selected_disks}")
        # Validate against sensitivity (which reflects is_live_os_disk)
        valid_selected_disks = {d for d in self.selected_disks if d in self.disk_widgets and self.disk_widgets[d]["row"].get_sensitive()}
        if len(valid_selected_disks) != len(self.selected_disks):
             print(f"  WARNING: Live OS disk found in selected_disks set. Correcting.")
             self.selected_disks = valid_selected_disks 
             
        print(f"  Selected disks AFTER validation: {self.selected_disks}") 
        
        can_proceed = (
            self.scan_completed and 
            len(self.selected_disks) > 0 and 
            self.partitioning_method is not None
        )
        print(f"  Scan completed: {self.scan_completed}") # DEBUG
        print(f"  Valid disks selected: {len(self.selected_disks) > 0}") # DEBUG
        print(f"  Method selected: {self.partitioning_method is not None}") # DEBUG
        print(f"  Setting Confirm button sensitive: {can_proceed}")
        self.complete_button.set_sensitive(can_proceed)
        
    def apply_settings_and_return(self, button):
        print(f"--- Apply Settings START ---")
        print(f"  Selected disks at start: {self.selected_disks}")
        
        # Re-validate conditions before proceeding
        self.update_complete_button_state()
        if not self.complete_button.get_sensitive():
             # This provides more specific feedback than just not proceeding
             if not self.scan_completed:
                 self.show_toast("Please scan for disks first.")
             elif len(self.selected_disks) == 0:
                 self.show_toast("Please select at least one usable disk.")
             elif self.partitioning_method is None:
                 self.show_toast("Please select a partitioning method.")
             else:
                 self.show_toast("Cannot confirm storage plan. Please check selections.") # Generic fallback
             return

        print(f"--- Confirming Storage Plan ---")
        print(f"  Selected Disks before generating commands: {list(self.selected_disks)}")
        print(f"  Partitioning Method: {self.partitioning_method}")
        
        # Initialize config_values
        config_values = {
            "method": self.partitioning_method,
            "target_disks": sorted(list(self.selected_disks)), 
            "commands": [],
            "partitions": []
        }

        if self.partitioning_method == "AUTOMATIC":
            # Check again just before using
            if not self.selected_disks:
                 print("!!! ERROR: No disks selected in apply_settings_and_return despite button being sensitive!")
                 self.show_toast("Internal Error: No disk selected.")
                 return
            primary_disk = sorted(list(self.selected_disks))[0]
            # Check if primary_disk is sensitive (should be)
            if primary_disk not in self.disk_widgets or not self.disk_widgets[primary_disk]["row"].get_sensitive():
                 print(f"!!! ERROR: Primary disk {primary_disk} is marked as unusable but was selected!")
                 self.show_toast(f"Internal Error: Cannot use disk {primary_disk}.")
                 return 
                 
            print(f"  Generating AUTOMATIC partitioning commands for: {primary_disk}")
            
            # Generate the command lists
            partition_prefix = "p" if "nvme" in primary_disk else ""
            wipe_cmd = generate_wipefs_command(primary_disk)
            parted_cmds = generate_gpt_commands(primary_disk)
            mkfs_cmds = generate_mkfs_commands(primary_disk, partition_prefix)
            all_commands = [wipe_cmd] + parted_cmds + mkfs_cmds
            config_values["commands"] = all_commands 
            part1_suffix = f"{partition_prefix}1"
            part2_suffix = f"{partition_prefix}2"
            config_values["partitions"] = [
                {"device": f"{primary_disk}{part1_suffix}", "mountpoint": "/boot/efi", "fstype": "vfat"},
                {"device": f"{primary_disk}{part2_suffix}", "mountpoint": "/", "fstype": "ext4"}
            ]
            if all_commands:
                 print(f"    Example command: {' '.join(shlex.quote(c) for c in all_commands[0])}")
                 
        elif self.partitioning_method == "MANUAL":
            print("  Manual Plan: (Not implemented - no commands generated)")
            # We should ideally detect existing partitions here if MANual was implemented

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
        
        # --- REMOVED REDUNDANT TODO/SIMULATION CODE --- 

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