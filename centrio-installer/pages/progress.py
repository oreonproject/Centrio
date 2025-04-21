# centrio_installer/pages/progress.py

import gi
import subprocess # For command execution
import os         # For creating directories
import shlex      # For logging commands safely
import threading  # For running install in background
import time       # For small delays maybe
import shutil     # For copying resolv.conf
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

# Import backend functions
from .. import backend

class ProgressPage(Gtk.Box):
    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, **kwargs)
        # Main box contains ScrolledWindow and potentially other fixed elements if needed
        self.set_vexpand(True)

        # --- Scrolled Window for Content --- 
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC) # Allow vertical scroll
        scrolled_window.set_vexpand(True)
        self.append(scrolled_window)
        
        # --- Content Box (Inside Scrolled Window) --- 
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content_box.set_margin_top(36)
        content_box.set_margin_bottom(36)
        content_box.set_margin_start(48)
        content_box.set_margin_end(48)
        # Removed valign=CENTER and vexpand=True from content_box, ScrolledWindow handles expansion
        scrolled_window.set_child(content_box)

        # Add widgets to the content_box
        title = Gtk.Label(label="Installing System")
        title.add_css_class("title-1")
        content_box.append(title)

        self.progress_bar = Gtk.ProgressBar(show_text=True, text="Starting installation...")
        self.progress_bar.set_pulse_step(0.1)
        content_box.append(self.progress_bar)

        self.progress_label = Gtk.Label(label="")
        self.progress_label.set_wrap(True)
        self.progress_label.set_xalign(0.0) # Align text to the left
        content_box.append(self.progress_label)

        # --- State Variables --- 
        self.progress_value = 0.0
        self.installation_error = None # Store any fatal error message
        self.target_root = "/mnt/sysimage" # Define the target mount point
        self.main_window = None # Store main window reference
        self.stop_requested = False # Flag to stop installation
        self.disk_config = None # Store disk_config for potential unmount later

    def _update_progress_text(self, text, fraction=None):
        """Helper to update progress bar text and optionally fraction via GLib.idle_add."""
        def update():
            # This code runs in the main GTK thread
            self.progress_label.set_text(text)
            if fraction is not None:
                # Keep track of the latest known overall fraction
                self.progress_value = max(self.progress_value, fraction) 
                clamped_fraction = max(0.0, min(self.progress_value, 1.0))
                self.progress_bar.set_fraction(clamped_fraction)
                self.progress_bar.set_text(f"{int(clamped_fraction * 100)}%")
            # Always log the text update
            print(f"Progress Update: {text} (Overall Fraction: {fraction if fraction is not None else '[text only]' })") 
        GLib.idle_add(update)

    def _attempt_unmount(self):
        """Attempts to unmount filesystems mounted under target_root."""
        print("Attempting to unmount target filesystems...")
        # Get mounted filesystems under the target path
        # Use findmnt to reliably get mount points in the correct order for unmounting (nested last)
        try:
            # Ensure buffers are flushed before checking mounts
            try: subprocess.run(["sync"], check=False, timeout=5) 
            except Exception: pass
            
            # -n: no header
            # -r: raw output
            # -o TARGET: only show target mount point
            # --target: filter by target path
            cmd = ["findmnt", "-nr", "-o", "TARGET", f"--target={self.target_root}"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
            mount_points = sorted([line.strip() for line in result.stdout.split('\n') if line.strip().startswith(self.target_root)], reverse=True)
            
            if not mount_points:
                print("  No filesystems found mounted under target root.")
                return

            print(f"  Will try to unmount: {mount_points}")
            for mp in mount_points:
                # Don't try to unmount the root mount itself if it wasn't found explicitly
                # (e.g., if only /mnt/sysimage/boot/efi was mounted)
                if mp == self.target_root and not any(p.get("mountpoint") == "/" for p in self.disk_config.get("partitions", [])):
                     continue
                     
                print(f"    Unmounting {mp}...")
                umount_cmd = ["umount", mp]
                try:
                    # Sync before trying to unmount
                    try: subprocess.run(["sync"], check=False, timeout=5) 
                    except Exception: pass
                    # Try normal unmount first
                    subprocess.run(umount_cmd, check=True, timeout=15, capture_output=True)
                    print(f"      Successfully unmounted {mp}")
                except subprocess.CalledProcessError as e:
                    print(f"      Warning: Failed to unmount {mp}: {e.stderr.strip()}. Trying lazy unmount...")
                    # Sync again before lazy unmount
                    try: subprocess.run(["sync"], check=False, timeout=5) 
                    except Exception: pass
                    # Fallback to lazy unmount
                    umount_lazy_cmd = ["umount", "-l", mp]
                    try:
                        subprocess.run(umount_lazy_cmd, check=True, timeout=5, capture_output=True)
                        print(f"        Lazy unmount successful for {mp}")
                    except Exception as lazy_e:
                        print(f"        Warning: Lazy unmount also failed for {mp}: {lazy_e}")
                except subprocess.TimeoutExpired:
                     print(f"      Warning: Timeout unmounting {mp}")
                except Exception as e:
                     print(f"      Warning: Error unmounting {mp}: {e}")
                     
            # Final sync after all attempts
            try: subprocess.run(["sync"], check=False, timeout=5) 
            except Exception: pass
                    
        except FileNotFoundError:
            print("  Warning: 'findmnt' command not found. Cannot automatically unmount.")
        except subprocess.CalledProcessError as e:
            print(f"  Warning: 'findmnt' failed: {e.stderr.strip()}. Cannot automatically unmount.")
        except Exception as e:
            print(f"  Warning: Error listing mounts: {e}. Cannot automatically unmount.")

    def _execute_storage_setup(self, disk_config):
        """Executes partitioning/formatting/mounting OR just mounting for manual."""
        self.disk_config = disk_config # Store for potential unmount later
        method = disk_config.get("method")
        commands = disk_config.get("commands", [])
        partitions = disk_config.get("partitions", [])
        target_disks = disk_config.get("target_disks", [])

        if method == "AUTOMATIC" and target_disks:
            primary_disk = target_disks[0]
            self._update_progress_text(f"Preparing disk {primary_disk}...", 0.01)
            
            # --- Stop udisks2 --- 
            stop_success, stop_err = backend._stop_service("udisks2.service")
            if not stop_success:
                 # Log warning but continue, maybe it wasn't running
                 print(f"Warning: Failed to stop udisks2 service (continuing): {stop_err}")
            else:
                 print("Stopped udisks2 service temporarily.")
                 time.sleep(1) # Give it a moment
                 
            # --- Deactivate LVM --- 
            lvm_success, lvm_err = backend._deactivate_lvm_on_disk(primary_disk, self._update_progress_text)
            if not lvm_success:
                 # Log warning but proceed cautiously
                 print(f"Warning: Failed to fully deactivate LVM on {primary_disk} (continuing): {lvm_err}")
            else:
                 print(f"LVM deactivation check complete for {primary_disk}.")
                 
            # --- Pre-emptive Unmount --- 
            self._update_progress_text(f"Checking existing mounts on {primary_disk}...", 0.02)
            mount_targets_to_check = set()
            device_paths_to_check = set([primary_disk])
            try:
                # Get all related device paths (disk + partitions)
                lsblk_cmd = ["lsblk", "-n", "-o", "PATH", "--raw", primary_disk]
                print(f"  Running: {' '.join(lsblk_cmd)}")
                lsblk_result = subprocess.run(lsblk_cmd, capture_output=True, text=True, check=False, timeout=10)
                if lsblk_result.returncode == 0:
                    found_paths = [line.strip() for line in lsblk_result.stdout.split('\n') if line.strip()]
                    print(f"  lsblk identified potential device paths: {found_paths}")
                    device_paths_to_check.update(found_paths)
                else:
                    print(f"  Warning: lsblk failed for {primary_disk} (rc={lsblk_result.returncode}), proceeding with just the base disk path.")
                
                # Check each device path for mounts using findmnt
                print(f"  Checking for mounts on paths: {list(device_paths_to_check)}")
                for dev_path in device_paths_to_check:
                    findmnt_cmd = ["findmnt", "-n", "-r", "-o", "TARGET", f"--source={dev_path}"]
                    # print(f"    Running: {' '.join(findmnt_cmd)}") # Verbose
                    result = subprocess.run(findmnt_cmd, capture_output=True, text=True, check=False, timeout=10)
                    if result.returncode == 0 and result.stdout.strip():
                        mount_points = [line.strip() for line in result.stdout.split('\n') if line.strip()]
                        print(f"    findmnt identified mount points for source {dev_path}: {mount_points}")
                        mount_targets_to_check.update(mount_points)
                    # Ignore errors or no output for individual checks

            except Exception as e:
                print(f"Warning: lsblk failed, proceeding with only {primary_disk}")
            
            try:
                # Sync before checking lsof
                try: subprocess.run(["sync"], check=False, timeout=5) 
                except Exception: pass
                # Check each mount point for active processes using lsof
                print(f"Running lsof on paths: {list(mount_targets_to_check)} to check for busy resources...")
                for path in sorted(list(mount_targets_to_check), reverse=True):
                    print(f"  Checking lsof on {path}...")
                    lsof_cmd = ["lsof", path]
                    lsof_success, lsof_err, lsof_stdout = backend._run_command(lsof_cmd, f"Check Processes on {path}", timeout=15)
                    
                    if lsof_stdout:
                        err_msg_detail = f"Device path {path} is busy. Processes found by lsof:\n{lsof_stdout}"
                        print(f"ERROR: {err_msg_detail}")
                        self.installation_error = err_msg_detail
                        return False # Fail immediately
                    elif not lsof_success and ("Cannot run program" in lsof_err or "Command not found" in lsof_err):
                        print(f"  Warning: lsof command not found for check on {path}.")
                    # else: lsof check passed for this path

            except Exception as e:
                print(f"Warning: findmnt check failed: {e}")
                
            # --- Attempt Unmount --- 
            unmount_failed = False
            if mount_targets_to_check:
                print(f"  Attempting to unmount: {sorted(list(mount_targets_to_check))}")
                for path in sorted(list(mount_targets_to_check), reverse=True):
                    print(f"    Unmounting {path}...")
                    umount_cmd = ["umount", path]
                    try:
                        # Sync before unmount
                        try: subprocess.run(["sync"], check=False, timeout=5) 
                        except Exception: pass
                        result = subprocess.run(umount_cmd, check=True, timeout=10, capture_output=True, text=True)
                        print(f"      Successfully unmounted {path} (stdout: {result.stdout.strip()}, stderr: {result.stderr.strip()}) ")
                        time.sleep(1) # Shorter sleep, sync is more important
                    except subprocess.CalledProcessError as e:
                        print(f"      Warning: Failed standard unmount {path} (rc={e.returncode}, stdout: {e.stdout.strip()}, stderr: {e.stderr.strip()}). Trying lazy unmount...")
                        # Sync before lazy unmount
                        try: subprocess.run(["sync"], check=False, timeout=5) 
                        except Exception: pass
                        umount_lazy_cmd = ["umount", "-l", path]
                        try:
                            result_lazy = subprocess.run(umount_lazy_cmd, check=True, timeout=10, capture_output=True, text=True)
                            print(f"        Lazy unmount successful for {path} (stdout: {result_lazy.stdout.strip()}, stderr: {result_lazy.stderr.strip()}) ")
                            time.sleep(1)
                        except Exception as lazy_e:
                            # Capture specific error for lazy unmount failure
                            lazy_err_msg = f"Failed to unmount {path} even with lazy option: {lazy_e}"
                            if isinstance(lazy_e, subprocess.CalledProcessError):
                                lazy_err_msg += f" (rc={lazy_e.returncode}, stdout: {lazy_e.stdout.strip()}, stderr: {lazy_e.stderr.strip()})"
                            print(f"      ERROR: {lazy_err_msg}")
                            self.installation_error = lazy_err_msg
                            unmount_failed = True
                            break # Stop trying to unmount if one fails fatally
                    except Exception as std_e:
                        # Catch other errors during standard unmount
                        std_err_msg = f"Error during standard unmount of {path}: {std_e}"
                        print(f"      ERROR: {std_err_msg}")
                        self.installation_error = std_err_msg
                        unmount_failed = True
                        break
            else:
                print("  No active mount points identified to unmount.")
                
            # Add explicit unmount attempt on the base device itself
            print(f"Attempting final unmount on base device {primary_disk}...")
            try:
                 # Sync before final base unmount
                 try: subprocess.run(["sync"], check=False, timeout=5) 
                 except Exception: pass
                 subprocess.run(["umount", primary_disk], check=False, capture_output=True, text=True, timeout=10)
            except Exception as base_umount_e:
                 print(f"  Warning: Error during final base device umount: {base_umount_e}")
                 
            if unmount_failed: # Check result from loop above
                 return False

            # --- Reread Partitions, Remove DM, Settle, Sync --- 
            print(f"Running partprobe on {primary_disk}...")
            try:
                partprobe_cmd = ["partprobe", primary_disk]
                pp_success, pp_err, _ = backend._run_command(partprobe_cmd, f"Reread partitions on {primary_disk}", timeout=30)
                if not pp_success: print(f"  Warning: partprobe failed: {pp_err}")
                time.sleep(2) # Reduced pause after partprobe, rely on settle
            except Exception as pp_e: print(f"Warning: Error running partprobe: {pp_e}")
            
            # Add dmsetup remove
            dm_success, dm_warn = backend._remove_dm_mappings(primary_disk, self._update_progress_text)
            if not dm_success: # Should always return True, but check anyway
                 print(f"Warning: dmsetup removal step indicated failure (ignored): {dm_warn}")
            if dm_warn: print(f"Note: {dm_warn}") # Print any warning message
            time.sleep(1) # Pause after dmsetup
                 
            print("Running udevadm settle...")
            try:
                # Run directly, might not need pkexec depending on context
                subprocess.run(["udevadm", "settle"], check=False, timeout=60) # Increased timeout
                print("  Udev settle complete.")
            except FileNotFoundError:
                 print("Warning: udevadm not found, cannot settle udev queue.")
            except Exception as settle_e:
                 print(f"Warning: Error running udevadm settle: {settle_e}")
                 
            print("Running sync command to flush buffers...")
            try:
                subprocess.run(["sync"], check=False, timeout=15)
                print("  Sync complete.")
                time.sleep(1) # Small pause after sync
            except Exception as sync_e:
                 print(f"Warning: Error running sync: {sync_e}")

            self._update_progress_text("Disk checks complete.", 0.04)

        # --- Execute Main Storage Actions ---
        if method == "AUTOMATIC":
            if not commands:
                self.installation_error = "Automatic partitioning selected, but no commands were generated."
                return False
                
            self._update_progress_text("Preparing storage devices...", 0.05)
            
            for i, cmd_list in enumerate(commands):
                cmd_name = cmd_list[0]
                progress_fraction = 0.1 + (0.20 * (i / len(commands))) # Adjusted fraction range
                
                # --- Final LSOF Check + Delay JUST before wipefs --- 
                if cmd_name == "wipefs" and primary_disk and primary_disk in cmd_list:
                    print(f"--- Performing FINAL check before {cmd_name} on {primary_disk} ---")
                    lsof_found_processes = False
                    # Get device paths again in case partprobe changed them
                    final_device_paths_to_lsof = set([primary_disk])
                    try:
                        lsblk_cmd = ["lsblk", "-n", "-o", "PATH", "--raw", primary_disk]
                        lsblk_result = subprocess.run(lsblk_cmd, capture_output=True, text=True, check=False, timeout=10)
                        if lsblk_result.returncode == 0:
                            final_device_paths_to_lsof.update([line.strip() for line in lsblk_result.stdout.split('\n') if line.strip()])
                    except Exception: pass # Ignore lsblk failure here
                    
                    print(f"Running final lsof on paths: {list(final_device_paths_to_lsof)}...")
                    # Sync before final lsof
                    try: subprocess.run(["sync"], check=False, timeout=5) 
                    except Exception: pass
                    for dev_path in final_device_paths_to_lsof:
                        lsof_cmd = ["lsof", dev_path]
                        lsof_success, lsof_err, lsof_stdout = backend._run_command(lsof_cmd, f"Final Check on {dev_path}", timeout=15)
                        if lsof_stdout:
                            err_msg_detail = f"FINAL CHECK FAILED: Path {dev_path} is busy:\n{lsof_stdout}"
                            print(f"ERROR: {err_msg_detail}")
                            self.installation_error = err_msg_detail
                            return False # Fail immediately
                        elif not lsof_success and ("Cannot run program" in lsof_err or "Command not found" in lsof_err):
                            print(f"  Warning: lsof command not found for final check on {dev_path}.")
                        # else: lsof check passed for this path
                        
                    if not lsof_found_processes: # Should always be False if we got here
                         print(f"  Final lsof checks passed for all paths.")
                         print(f"Adding 8 second delay before executing {cmd_name}...") # Increased delay
                         try: subprocess.run(["sync"], check=False, timeout=5) # Sync before delay
                         except Exception: pass
                         time.sleep(8) # Increased from 5 to 8 seconds
                         try: subprocess.run(["sync"], check=False, timeout=5) # Sync after delay
                         except Exception: pass
                    else:
                         # This case should not be reached due to return above
                         return False 
                
                # --- Execute command --- 
                quoted_cmd = ' '.join(shlex.quote(c) for c in cmd_list)
                print(f"--- ABOUT TO EXECUTE STORAGE COMMAND: {quoted_cmd} ---")
                
                self._update_progress_text(f"Running: {cmd_name}...", progress_fraction)
                success, err, _ = backend._run_command(cmd_list, f"Storage Step: {cmd_name}", self._update_progress_text, timeout=120) # Increased timeout for mkfs/parted
                if not success:
                    self.installation_error = err
                    # Should we restart udisks2 here on failure?
                    # backend._start_service("udisks2.service") # Maybe add this?
                    return False
                    
            self._update_progress_text("Partitioning and formatting complete.", 0.30) # End fraction adjusted
            
        elif method == "MANUAL":
            print("Manual partitioning selected. Skipping wipefs/parted/mkfs commands.")
            self._update_progress_text("Using existing partitions...", 0.25)
            # Partitions should have been detected by DiskPage and passed in disk_config
            if not partitions:
                 self.installation_error = "Manual partitioning selected, but no partitions were detected or passed."
                 return False
        else:
            self.installation_error = f"Invalid or missing partitioning method: {method}"
            return False
            
        # --- Mount Filesystems (Common to Automatic & Manual) ---
        if not partitions:
            self.installation_error = f"No partition details found in config for {method} method, cannot mount."
            return False
            
        self._update_progress_text("Mounting filesystems...", 0.3)
        try:
            os.makedirs(self.target_root, exist_ok=True)
        except OSError as e:
            self.installation_error = f"Failed to create root mount point {self.target_root}: {e}"
            return False
            
        mount_progress_start = 0.3
        mount_progress_end = 0.35
        
        # Corrected sort order: Mount / first, then others like /boot/efi
        # Assign lower number to / mountpoint for sorting
        sorted_partitions = sorted(partitions, key=lambda p: 0 if p.get("mountpoint") == "/" else (1 if p.get("mountpoint") == "/boot/efi" else 2))
        
        print(f"Mount order determined: {[p.get('mountpoint') for p in sorted_partitions]}")
        
        for i, part_info in enumerate(sorted_partitions):
            device = part_info.get("device")
            mountpoint = part_info.get("mountpoint")
            fstype = part_info.get("fstype") # Get fstype for potential mount options
            if not device or not mountpoint:
                 print(f"Skipping partition due to missing device or mountpoint: {part_info}")
                 continue
                 
            full_mount_path = os.path.join(self.target_root, mountpoint.lstrip('/'))
            progress_fraction = mount_progress_start + (mount_progress_end - mount_progress_start) * (i / len(sorted_partitions))
            
            # Create mount point directory *before* attempting mount
            self._update_progress_text(f"Creating mount point {full_mount_path}...", progress_fraction)
            try:
                 # Only create if it's not the root mountpoint itself (which already exists)
                 if full_mount_path != self.target_root:
                     os.makedirs(full_mount_path, exist_ok=True)
            except OSError as e:
                 err_msg = f"Failed to create mount point {full_mount_path}: {e}"
                 print(f"ERROR: {err_msg}")
                 self.installation_error = err_msg
                 self._attempt_unmount() # Cleanup previously mounted
                 return False

            # Build mount command (add options if needed, e.g., for vfat)
            mount_cmd = ["mount", device, full_mount_path]
            if fstype == "vfat":
                 # Add common options for FAT filesystems like EFI
                 mount_cmd.insert(1, "-o")
                 mount_cmd.insert(2, "rw,relatime,fmask=0077,dmask=0077,codepage=437,iocharset=iso8859-1,shortname=mixed,errors=remount-ro")
                 
            mount_desc = f"Mount {device} ({fstype}) -> {full_mount_path}"
            self._update_progress_text(mount_desc + "...", progress_fraction + 0.01)
            print(f"Running on host: {mount_desc} -> {' '.join(shlex.quote(c) for c in mount_cmd)}")
            try:
                 # Use subprocess.run directly as we are already root
                 result = subprocess.run(mount_cmd, capture_output=True, text=True, check=True, timeout=30)
                 print(f"  Mount successful. stdout: {result.stdout.strip()}, stderr: {result.stderr.strip()}")
            except subprocess.CalledProcessError as e:
                 err_msg = f"Failed to mount {device} to {full_mount_path} (rc={e.returncode}): {e.stderr.strip() or e.stdout.strip()}"
                 print(f"ERROR: {err_msg}")
                 self.installation_error = err_msg
                 self._attempt_unmount() # Cleanup previously mounted
                 return False
            except FileNotFoundError:
                 err_msg = "Mount command failed: 'mount' executable not found."
                 print(f"ERROR: {err_msg}")
                 self.installation_error = err_msg
                 self._attempt_unmount()
                 return False
            except Exception as e:
                 # Catch other potential errors like timeouts
                 err_msg = f"Unexpected error mounting {device}: {e}"
                 print(f"ERROR: {err_msg}")
                 self.installation_error = err_msg
                 self._attempt_unmount()
                 return False

        self._update_progress_text("Filesystems mounted successfully.", mount_progress_end)
        return True

    # --- Backend Execution Methods --- 

    def _configure_system(self, config_data):
        """Configures system settings using backend function."""
        if self.stop_requested: return False, "Stop requested"
        self._update_progress_text("Configuring system settings...", 0.4)
        
        success, err = backend.configure_system_in_container(
            self.target_root, 
            config_data, 
            progress_callback=self._update_progress_text
        )
        
        if success:
            self._update_progress_text("System settings configured.", 0.45)
        else:
            self.installation_error = err
            
        return success

    def _create_user(self, config_data):
        """Creates user account using backend function."""
        if self.stop_requested: return False, "Stop requested"
        user_config = config_data.get('user')
        if not user_config or not user_config.get('username'):
            print("Skipping user creation (no user configured).")
            self._update_progress_text("User creation skipped.", 0.5)
            return True # Not an error to skip
            
        # TODO: Retrieve password securely if needed
        # For now, assume it might be missing or needs to be handled
        if 'password' not in user_config:
             print("Warning: Password missing for user creation, attempting without.")
             # Or set a default, or fail?
             # Forcing failure for safety now
             self.installation_error = "Password missing in configuration for user creation."
             return False
             
        username = user_config['username']
        self._update_progress_text(f"Creating user {username}...", 0.5)
        
        success, err = backend.create_user_in_container(
            self.target_root, 
            user_config, 
            progress_callback=self._update_progress_text
        )
        
        if success:
            self._update_progress_text(f"User {username} created.", 0.55)
        else:
            self.installation_error = err

        return success

    def _install_packages(self, config_data):
        """Installs packages using backend function."""
        if self.stop_requested: return False, "Stop requested"
        payload_config = config_data.get('payload', {})
        payload_type = payload_config.get('payload_type', 'DNF') 
        
        if payload_type != 'DNF':
             self.installation_error = f"Unsupported payload type: {payload_type}" # Only DNF supported now
             return False
             
        # Add message here before calling backend
        self._update_progress_text(f"Starting package installation via {payload_type} (This may take a while)...", 0.35) 
        
        # Call backend function, passing the progress callback
        success, err = backend.install_packages_dnf(
            self.target_root,
            progress_callback=self._update_progress_text 
        )
        
        # Note: Progress fractions inside install_packages_dnf range from 0.0 to 1.0,
        # mapped to the overall progress range 0.35 -> 0.8 in _run_installation_steps scaling below.
        # We just update the final message here.
        if success:
            self._update_progress_text("Package installation complete.", 0.8) # Final fraction for this step
        else:
             self.installation_error = err # Error already set by backend ideally
             
        return success

    def _enable_network_manager_step(self, config_data):
        """Step wrapper for enabling NetworkManager."""
        if self.stop_requested: return False, "Stop requested"
        # No initial message needed, backend function sends one
        success, warning = backend.enable_network_manager(
             self.target_root, 
             progress_callback=self._update_progress_text
        )
        # Success is always True unless a fatal error occurred in _run_command
        # A warning is not considered a failure for this step
        if not success: # Should only happen if _run_command fails badly
             self.installation_error = warning
             return False 
        return True 

    def _install_bootloader(self, config_data):
        """Installs bootloader using backend function."""
        if self.stop_requested: return False, "Stop requested"
        bootloader_config = config_data.get('bootloader', {})
        disk_config = config_data.get('disk', {})
        
        if not bootloader_config.get('install_bootloader', False):
            print("Skipping bootloader installation.")
            self._update_progress_text("Bootloader installation skipped.", 0.9)
            return True

        # Determine primary disk and EFI partition (if exists)
        primary_disk = disk_config.get('target_disks', [None])[0]
        efi_partition_device = None
        partitions = disk_config.get('partitions', [])
        for part in partitions:
            if part.get('mountpoint') == '/boot/efi':
                efi_partition_device = part.get('device')
                print(f"Found EFI partition device: {efi_partition_device}")
                break
        
        if not primary_disk:
             self.installation_error = "Cannot determine target disk for bootloader installation."
             return False
        # Note: We might proceed even without an EFI partition found here, 
        # backend function will handle BIOS vs UEFI logic.

        self._update_progress_text("Installing bootloader...", 0.9)
        
        success, err, _ = backend.install_bootloader_in_container(
            self.target_root, 
            primary_disk, 
            efi_partition_device, # Pass EFI partition device
            progress_callback=self._update_progress_text
        )
        
        if success:
            self._update_progress_text("Bootloader installed.", 0.95)
        else:
            self.installation_error = err
            
        return success
        
    # --- Main Installation Flow --- 

    def start_installation(self, main_window, config_data):
        """Start the actual installation process sequentially."""
        self.main_window = main_window # Store ref for navigation
        self.stop_requested = False # Reset stop flag
        print("Starting installation with config:", config_data)
        self.progress_value = 0.0
        self.installation_error = None 
        self.progress_bar.set_fraction(0.0)
        self.progress_label.set_text("Preparing installation...")
        
        # Run installation steps in a separate thread to avoid blocking UI
        # Use GLib.idle_add to update UI from the thread
        thread = threading.Thread(target=self._run_installation_steps, args=(config_data,))
        thread.daemon = True # Allow app to exit even if thread hangs
        thread.start()

    def _run_installation_steps(self, config_data):
        """Worker function to run installation steps sequentially."""
        steps = [ 
             # Updated fractions slightly 
             (self._execute_storage_setup,      config_data.get('disk', {}), 0.00,  0.30), # 30%
             (self._install_packages,           config_data,             0.30,  0.75), # 45%
             (self._configure_system,           config_data,             0.75,  0.80), # 5%
             (self._create_user,                config_data,             0.80,  0.85), # 5%
             (self._enable_network_manager_step,config_data,             0.85,  0.87), # 2%
             (self._install_bootloader,         config_data,             0.87,  0.97), # 10%
             # Post-install?                                               0.97,  1.00  # 3%
        ]
        
        final_success = True
        try:
            # Main step loop
            for func, data, start_fraction, end_fraction in steps:
                if self.stop_requested:
                    print("Installation stopped by user request.")
                    final_success = False
                    break
                
                step_success = func(data) 
                
                # --- Add explicit /etc check+create after package install ---
                if func == self._install_packages and step_success:
                    etc_path = os.path.join(self.target_root, "etc")
                    resolv_conf_target = os.path.join(etc_path, "resolv.conf")
                    host_resolv_conf = "/etc/resolv.conf"
                    
                    # Ensure /etc exists
                    if not os.path.exists(etc_path):
                        print(f"Warning: {etc_path} not found after package install. Creating it...")
                        try:
                            os.makedirs(etc_path, exist_ok=True)
                            print(f"Successfully created {etc_path}.")
                        except OSError as e:
                            print(f"ERROR: Failed to create {etc_path}: {e}")
                            self.installation_error = f"Failed to create essential directory {etc_path}: {e}"
                            step_success = False # Mark step as failed
                    
                    # Copy host resolv.conf if /etc creation succeeded
                    if step_success and os.path.exists(host_resolv_conf):
                        print(f"Copying {host_resolv_conf} to {resolv_conf_target}...")
                        try:
                            shutil.copy2(host_resolv_conf, resolv_conf_target)
                            print(f"Successfully copied resolv.conf.")
                        except Exception as copy_e:
                            # Log warning but don't necessarily fail the whole install?
                            # Chroot might still work for some things without network.
                            print(f"Warning: Failed to copy {host_resolv_conf} to {resolv_conf_target}: {copy_e}")
                    elif step_success and not os.path.exists(host_resolv_conf):
                         print(f"Warning: Host {host_resolv_conf} not found. Cannot copy to target.")
                         
                # ---------------------------------------------------------
                
                if not step_success:
                    final_success = False
                    if not self.installation_error:
                         self.installation_error = f"Step {func.__name__} failed without error message."
                    self._update_progress_text(self.installation_error, start_fraction)
                    break
                else:
                     final_step_message = f"Step {func.__name__} complete."
                     self._update_progress_text(final_step_message, end_fraction)
        
        finally:
             # --- Ensure udisks2 is restarted --- 
             print("Installation sequence finished or stopped. Ensuring udisks2 service is started...")
             backend._start_service("udisks2.service")
        
        # --- Finalize UI --- 
        def finalize_ui():
            if final_success and not self.stop_requested:
                final_message = "Installation finished successfully!"
                self._update_progress_text(final_message, 1.0)
                GLib.timeout_add(1500, self.main_window.navigate_to_page, "finished")
            elif self.stop_requested:
                 self._update_progress_text("Installation stopped.", self.progress_bar.get_fraction())
                 self._attempt_unmount() 
            else:
                error_msg = f"Installation failed: {self.installation_error}"
                self._update_progress_text(error_msg, self.progress_bar.get_fraction())
                self._attempt_unmount() 
        
        GLib.idle_add(finalize_ui)

    def stop_installation(self):
        """Signals the installation thread to stop and attempts unmount."""
        print("Stop installation requested.")
        if not self.stop_requested: # Prevent multiple calls
            self.stop_requested = True
            # Attempt unmount immediately after stop request
            # This might race with the thread, but better than nothing?
            # Consider signaling the thread to cleanup instead.
            # For now, just call it here.
            self._attempt_unmount()