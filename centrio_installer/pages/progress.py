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
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18, **kwargs)
        self.set_margin_top(36)
        self.set_margin_bottom(36)
        self.set_margin_start(48)
        self.set_margin_end(48)
        self.set_valign(Gtk.Align.CENTER)
        self.set_vexpand(True)

        title = Gtk.Label(label="Installing System")
        title.add_css_class("title-1")
        self.append(title)

        self.progress_bar = Gtk.ProgressBar(show_text=True, text="Starting installation...")
        self.progress_bar.set_pulse_step(0.1)
        self.append(self.progress_bar)

        self.progress_label = Gtk.Label(label="")
        self.progress_label.set_wrap(True)
        self.append(self.progress_label)

        self.progress_value = 0.0
        self.installation_error = None # Store any fatal error message
        self.target_root = "/mnt/sysimage" # Define the target mount point
        self.main_window = None # Store main window reference
        self.stop_requested = False # Flag to stop installation
        self.disk_config = None # Store disk_config for potential unmount later

    def _update_progress_text(self, text, fraction=None):
        """Helper to update progress bar text and optionally fraction."""
        def update():
            self.progress_label.set_text(text)
            if fraction is not None:
                self.progress_bar.set_fraction(fraction)
                self.progress_bar.set_text(f"{int(fraction * 100)}%")
            print(f"Progress: {text} ({fraction})") # Log progress
        GLib.idle_add(update)
        # Allow UI updates during long steps
        while Gtk.events_pending():
            Gtk.main_iteration()
        
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
                # Use lazy unmount? (-l) Might hide issues but prevent blocking.
                # Or force? (-f) Can be dangerous.
                # Try normal unmount first.
                umount_cmd = ["umount", mp]
                try:
                    subprocess.run(umount_cmd, check=True, timeout=15, capture_output=True)
                    print(f"      Successfully unmounted {mp}")
                except subprocess.CalledProcessError as e:
                    print(f"      Warning: Failed to unmount {mp}: {e.stderr.strip()}")
                    # Consider trying lazy unmount as fallback?
                    # umount_lazy_cmd = ["umount", "-l", mp]
                    # try: ... except: ...
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
        """Executes partitioning, formatting, and mounting commands."""
        commands = disk_config.get("commands", [])
        partitions = disk_config.get("partitions", [])
        method = disk_config.get("method")

        if not commands or method != "AUTOMATIC":
            print(f"Skipping storage setup: No commands generated or method is {method}.")
            # If manual was selected and had no commands, this is expected.
            # If automatic failed to generate commands, that's an error handled earlier.
            return True # Treat as success for now
        
        self._update_progress_text("Preparing storage devices...", 0.05)
        
        # --- Execute Partitioning/Formatting Commands ---
        for i, cmd_list in enumerate(commands):
            cmd_name = cmd_list[0]
            progress_fraction = 0.1 + (0.15 * (i / len(commands))) # Allocate ~15% progress
            # Use the backend runner
            success, err = backend._run_command(cmd_list, f"Storage Step: {cmd_name}", self._update_progress_text, timeout=60)
            if not success:
                self.installation_error = err
                return False
                
        self._update_progress_text("Partitioning and formatting complete.", 0.25)
        
        # --- Mount Filesystems ---
        if not partitions:
            print("Warning: No partition details found in config, cannot mount.")
            # This might be okay if manual partitioning was intended to be handled differently
            return True
            
        self._update_progress_text("Mounting filesystems...", 0.3)
        try:
            # Ensure root mount point exists
            os.makedirs(self.target_root, exist_ok=True)
        except OSError as e:
            self.installation_error = f"Failed to create root mount point {self.target_root}: {e}"
            print(f"ERROR: {self.installation_error}")
            return False
            
        # Mount in order (usually ESP then /)
        mount_progress_start = 0.3
        mount_progress_end = 0.35
        for i, part_info in enumerate(partitions):
            device = part_info.get("device")
            mountpoint = part_info.get("mountpoint")
            # fstype = part_info.get("fstype") # Not needed for mount command
            
            if not device or not mountpoint:
                print(f"Warning: Skipping mount for incomplete partition info: {part_info}")
                continue
                
            # Create the specific mount point under the target root
            full_mount_path = os.path.join(self.target_root, mountpoint.lstrip('/'))
            progress_fraction = mount_progress_start + (mount_progress_end - mount_progress_start) * (i / len(partitions))
            self._update_progress_text(f"Creating mount point {full_mount_path}...", progress_fraction)
            try:
                 os.makedirs(full_mount_path, exist_ok=True)
            except OSError as e:
                 self.installation_error = f"Failed to create mount point {full_mount_path}: {e}"
                 print(f"ERROR: {self.installation_error}")
                 return False

            # Build mount command
            mount_cmd = ["mount", device, full_mount_path]
            # Add fstype if specified (optional for mount command, but good practice)
            # if fstype:
            #    mount_cmd.extend(["-t", fstype])
            
            self._update_progress_text(f"Mounting {device} at {full_mount_path}...", progress_fraction)
            success, err = backend._run_command(mount_cmd, f"Mount {device}", self._update_progress_text, timeout=15)
            if not success:
                self.installation_error = err
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
             
        self._update_progress_text(f"Installing packages via {payload_type}...", 0.6)
        
        # Pass the progress callback for potential future use inside backend
        success, err = backend.install_packages_dnf(
            self.target_root,
            progress_callback=self._update_progress_text 
        )
        
        if success:
            self._update_progress_text("Package installation complete.", 0.8)
        else:
             self.installation_error = err
             
        return success

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
        steps = [
            (self._execute_storage_setup, config_data.get('disk', {})), # 0.0 - 0.35
            (self._configure_system, config_data),                   # 0.4 - 0.45
            (self._create_user, config_data),                        # 0.5 - 0.55
            (self._install_packages, config_data),                   # 0.6 - 0.8
            (self._install_bootloader, config_data),                 # 0.9 - 0.95
            # Add post-install step here if needed
        ]

        success = True
        for func, data in steps:
            if self.stop_requested:
                print("Installation stopped by user request.")
                success = False
                # Don't set installation_error if stopped by user
                break
            
            # Call the step function (which now returns success boolean)
            step_success = func(data) 
            if not step_success:
                success = False
                # Error message should be set in self.installation_error by the failed function
                if not self.installation_error:
                     self.installation_error = f"Step {func.__name__} failed without error message."
                break
        
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