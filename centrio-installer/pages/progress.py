# centrio_installer/pages/progress.py

import gi
import subprocess # For command execution
import os         # For creating directories
import shlex      # For logging commands safely
import threading  # For running install in background
import time       # For small delays maybe
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
                    # Try normal unmount first
                    subprocess.run(umount_cmd, check=True, timeout=15, capture_output=True)
                    print(f"      Successfully unmounted {mp}")
                except subprocess.CalledProcessError as e:
                    print(f"      Warning: Failed to unmount {mp}: {e.stderr.strip()}. Trying lazy unmount...")
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

        # --- Pre-emptive Unmount (Needed for Automatic) ---
        if method == "AUTOMATIC" and target_disks:
            primary_disk = target_disks[0]
            self._update_progress_text(f"Checking existing mounts on {primary_disk} and its partitions...", 0.01)
            print(f"Attempting pre-emptive unmount of partitions on {primary_disk}...")
            
            # --- Find potential mount points using lsblk + findmnt per partition --- 
            mount_targets_to_check = set()
            device_paths_to_check = set([primary_disk]) # Start with the base disk
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

            except FileNotFoundError:
                 print("  Warning: 'lsblk' or 'findmnt' command not found. Cannot reliably check for mounts.")
            except Exception as e:
                print(f"  Warning: Error during mount check: {e}")

            # --- Attempt Unmount --- 
            unmount_failed = False
            if mount_targets_to_check:
                print(f"  Attempting to unmount: {sorted(list(mount_targets_to_check))}")
                for path in sorted(list(mount_targets_to_check), reverse=True):
                    print(f"    Unmounting {path}...")
                    umount_cmd = ["umount", path]
                    try:
                        result = subprocess.run(umount_cmd, check=True, timeout=10, capture_output=True, text=True)
                        print(f"      Successfully unmounted {path} (stdout: {result.stdout.strip()}, stderr: {result.stderr.strip()}) ")
                        time.sleep(5) # Increased sleep to 5 seconds
                    except subprocess.CalledProcessError as e:
                        print(f"      Warning: Failed standard unmount {path} (rc={e.returncode}, stdout: {e.stdout.strip()}, stderr: {e.stderr.strip()}). Trying lazy unmount...")
                        umount_lazy_cmd = ["umount", "-l", path]
                        try:
                            result_lazy = subprocess.run(umount_lazy_cmd, check=True, timeout=10, capture_output=True, text=True)
                            print(f"        Lazy unmount successful for {path} (stdout: {result_lazy.stdout.strip()}, stderr: {result_lazy.stderr.strip()}) ")
                            time.sleep(5) # Increased sleep to 5 seconds
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
                
            if unmount_failed:
                return False # Exit if unmount failed

            # --- Run partprobe, udevadm settle and sync --- 
            print(f"Running partprobe on {primary_disk}...")
            try:
                partprobe_cmd = ["partprobe", primary_disk]
                # Use backend runner as partprobe often needs root
                pp_success, pp_err, _ = backend._run_command(partprobe_cmd, f"Reread partitions on {primary_disk}", timeout=30)
                if pp_success:
                     print("  Partprobe successful.")
                else:
                     # Log error but don't necessarily fail, maybe device has no partitions yet
                     print(f"  Warning: partprobe failed for {primary_disk}: {pp_err}")
                time.sleep(2) # Pause after partprobe
            except Exception as pp_e:
                 print(f"Warning: Error running partprobe: {pp_e}")
                 
            print("Running udevadm settle...")
            try:
                # Run directly, might not need pkexec depending on context
                subprocess.run(["udevadm", "settle"], check=False, timeout=30)
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

            # --- lsof Check (Targeted) --- 
            self._update_progress_text(f"Checking for processes using {primary_disk} or its partitions...", 0.03)
            lsof_found_processes = False
            # Re-fetch device paths in case partprobe changed something? (Probably not needed)
            final_device_paths_to_lsof = device_paths_to_check # Use paths found earlier
            print(f"Running lsof on paths: {list(final_device_paths_to_lsof)} to check for busy resources...")
            
            for dev_path in final_device_paths_to_lsof:
                print(f"  Checking lsof on {dev_path}...")
                lsof_cmd = ["lsof", dev_path]
                lsof_success, lsof_err, lsof_stdout = backend._run_command(lsof_cmd, f"Check Processes on {dev_path}", timeout=15)
                
                if lsof_stdout:
                    err_msg_detail = f"Device path {dev_path} is busy. Processes found by lsof:\n{lsof_stdout}"
                    print(f"ERROR: {err_msg_detail}")
                    self.installation_error = err_msg_detail
                    lsof_found_processes = True
                    break # Found processes on one path, no need to check others
                elif not lsof_success and ("Cannot run program" in lsof_err or "Command not found" in lsof_err):
                     print(f"  Warning: lsof command not found or failed to execute for {dev_path}. Cannot verify device is free. Error: {lsof_err}")
                     # Continue checking other paths, but maybe flag this?
                # else: # lsof ran successfully with no output for this path
                    # print(f"    lsof check passed for {dev_path}.")

            if lsof_found_processes:
                return False # A process was found holding one of the device paths
            else:
                 print(f"  lsof checks passed for all paths: {list(final_device_paths_to_lsof)}.")
                
            self._update_progress_text("Pre-mount and process checks complete.", 0.04)

        # --- Execute Main Storage Actions ---
        if method == "AUTOMATIC":
            if not commands:
                self.installation_error = "Automatic partitioning selected, but no commands were generated."
                return False
                
            self._update_progress_text("Preparing storage devices...", 0.05)
            
            # Execute Partitioning/Formatting Commands
            for i, cmd_list in enumerate(commands):
                cmd_name = cmd_list[0]
                progress_fraction = 0.1 + (0.15 * (i / len(commands)))
                
                # Increase delay before wipefs
                if cmd_name == "wipefs" and primary_disk and primary_disk in cmd_list:
                     print(f"Adding 5 second delay before executing {cmd_name} on {primary_disk}...")
                     time.sleep(5)
                     
                # Use the backend runner (handles pkexec)
                success, err, _ = backend._run_command(cmd_list, f"Storage Step: {cmd_name}", self._update_progress_text, timeout=60)
                if not success:
                    self.installation_error = err
                    return False
            self._update_progress_text("Partitioning and formatting complete.", 0.25)
            
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

        primary_disk = disk_config.get('auto_partition_plan', {}).get('primary_disk')
        if not primary_disk:
             # Try getting first target disk if plan wasn't populated (e.g., manual mode placeholder)
             primary_disk = disk_config.get('target_disks', [None])[0]
        
        if not primary_disk:
             self.installation_error = "Cannot determine target disk for bootloader installation."
             return False

        self._update_progress_text("Installing bootloader...", 0.9)
        
        success, err = backend.install_bootloader_in_container(
            self.target_root, 
            primary_disk, 
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
        # Adjusted order to include NetworkManager enable step
        # Fractions need review for balance
        steps = [
            # Func                             # Data                   # Start% End%   Duration%
            (self._execute_storage_setup,      config_data.get('disk', {}), 0.00,  0.35), # 35%
            (self._install_packages,           config_data,             0.35,  0.80), # 45%
            (self._configure_system,           config_data,             0.80,  0.85), # 5%
            (self._create_user,                config_data,             0.85,  0.90), # 5%
            (self._enable_network_manager_step,config_data,             0.90,  0.92), # 2% (Separate, quick step)
            (self._install_bootloader,         config_data,             0.92,  0.97), # 5%
            # Post-install?                                               0.97,  1.00  # 3%
        ]

        success = True
        cumulative_progress = 0.0
        for func, data, start_fraction, end_fraction in steps:
            if self.stop_requested:
                print("Installation stopped by user request.")
                success = False
                break
            
            # --- Define a scaled progress callback --- 
            step_duration_fraction = end_fraction - start_fraction
            def scaled_progress_callback(message, step_fraction):
                # Clamp step_fraction between 0.0 and 1.0
                step_fraction_clamped = max(0.0, min(step_fraction, 1.0))
                # Calculate overall progress
                overall_fraction = start_fraction + (step_fraction_clamped * step_duration_fraction)
                # Update UI
                self._update_progress_text(message, overall_fraction)
            
            # Run the actual step function (passing the original callback for text updates)
            step_success = func(data) 
            
            if not step_success:
                success = False
                if not self.installation_error:
                     self.installation_error = f"Step {func.__name__} failed without error message."
                # Update progress bar to start_fraction on failure? Or keep last known?
                self._update_progress_text(self.installation_error, start_fraction) # Show error and reset bar to step start
                break
            else:
                 # Update progress bar to the end fraction for this step on success
                 # We might need a final message from the step? Assume generic for now.
                 final_step_message = f"Step {func.__name__} complete."
                 self._update_progress_text(final_step_message, end_fraction)
        
        # --- Finalize --- 
        def finalize_ui():
            if success and not self.stop_requested:
                final_message = "Installation finished successfully!"
                self._update_progress_text(final_message, 1.0)
                # Navigate to finished page after delay
                GLib.timeout_add(1500, self.main_window.navigate_to_page, "finished")
            elif self.stop_requested:
                 self._update_progress_text("Installation stopped.", self.progress_bar.get_fraction())
                 self._attempt_unmount() # Attempt cleanup
            else:
                # Failure case
                error_msg = f"Installation failed: {self.installation_error}"
                self._update_progress_text(error_msg, self.progress_bar.get_fraction())
                self._attempt_unmount() # Attempt cleanup
        
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