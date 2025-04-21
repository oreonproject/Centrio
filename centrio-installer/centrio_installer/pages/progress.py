import os
import subprocess
import shlex

class ProgressPage(Gtk.Box):
    def _update_progress_text(self, text, fraction=None):
        """Helper to update progress bar text and optionally fraction via GLib.idle_add."""
        def update():
            # This code runs in the main GTK thread
            self.progress_label.set_text(text)
            if fraction is not None:
                self.progress_bar.set_fraction(fraction)
                self.progress_bar.set_text(f"{int(fraction * 100)}%")
            print(f"Progress: {text} ({fraction})") # Log progress
        # Schedule the UI update on the main thread
        GLib.idle_add(update)
        # Removed the Gtk.events_pending() loop 

    def _execute_storage_setup(self, disk_config):
        """Executes partitioning/formatting/mounting OR just mounting for manual."""
        self.disk_config = disk_config # Store for potential unmount later
        method = disk_config.get("method")
        commands = disk_config.get("commands", [])
        partitions = disk_config.get("partitions", [])
        
        if method == "MANUAL":
            print("Manual partitioning selected. Skipping wipefs/parted/mkfs commands.")
            # Set progress past the formatting stage
            self._update_progress_text("Using existing partitions...", 0.25)
        elif method == "AUTOMATIC":
            if not commands:
                self.installation_error = "Automatic partitioning selected, but no commands were generated."
                return False
                
            self._update_progress_text("Preparing storage devices...", 0.05)
            # --- Execute Partitioning/Formatting Commands (Automatic Only) ---
            for i, cmd_list in enumerate(commands):
                cmd_name = cmd_list[0]
                progress_fraction = 0.1 + (0.15 * (i / len(commands))) 
                success, err, _ = backend._run_command(cmd_list, f"Storage Step: {cmd_name}", self._update_progress_text, timeout=60)
                if not success:
                    self.installation_error = err
                    return False
            self._update_progress_text("Partitioning and formatting complete.", 0.25)
        else:
            # No method or unknown method
            self.installation_error = f"Invalid or missing partitioning method: {method}"
            return False
            
        # --- Mount Filesystems (Common to Automatic & Manual) ---
        if not partitions:
            # For manual, this means detection failed. For auto, means generation failed.
            self.installation_error = f"No partition details found in config for {method} method, cannot mount."
            return False
            
        self._update_progress_text("Mounting filesystems...", 0.3)
        try:
            os.makedirs(self.target_root, exist_ok=True)
        except OSError as e:
            self.installation_error = f"Failed to create root mount point {self.target_root}: {e}"
            print(f"ERROR: {self.installation_error}")
            return False
            
        mount_progress_start = 0.3
        mount_progress_end = 0.35
        # Mount in order: EFI first, then root
        sorted_partitions = sorted(partitions, key=lambda p: 0 if p.get("mountpoint") == "/boot/efi" else (1 if p.get("mountpoint") == "/" else 2))
        
        for i, part_info in enumerate(sorted_partitions):
            device = part_info.get("device")
            mountpoint = part_info.get("mountpoint")
            
            if not device or not mountpoint:
                print(f"Warning: Skipping mount for incomplete partition info: {part_info}")
                continue
                
            full_mount_path = os.path.join(self.target_root, mountpoint.lstrip('/'))
            progress_fraction = mount_progress_start + (mount_progress_end - mount_progress_start) * (i / len(sorted_partitions))
            self._update_progress_text(f"Creating mount point {full_mount_path}...", progress_fraction)
            try:
                 os.makedirs(full_mount_path, exist_ok=True)
            except OSError as e:
                 self.installation_error = f"Failed to create mount point {full_mount_path}: {e}"
                 print(f"ERROR: {self.installation_error}")
                 return False

            mount_cmd = ["mount", device, full_mount_path]
            # Use run_host_command for mount as it doesn't need container/pkexec usually
            # success, err, _ = backend._run_command(mount_cmd, f"Mount {device}", self._update_progress_text, timeout=15)
            # Using a direct call here might be simpler if pkexec isn't strictly needed for mount
            try:
                 print(f"Running on host: Mount {device} -> {' '.join(shlex.quote(c) for c in mount_cmd)}")
                 result = subprocess.run(mount_cmd, capture_output=True, text=True, check=True, timeout=15)
                 print(f"  SUCCESS: Mounted {device} at {full_mount_path}.")
                 success = True
            except Exception as e:
                 err_detail = "Unknown error"
                 if isinstance(e, subprocess.CalledProcessError):
                     err_detail = e.stderr.strip() or f"Exit code {e.returncode}"
                 elif isinstance(e, FileNotFoundError):
                     err_detail = "mount command not found."
                 elif isinstance(e, subprocess.TimeoutExpired):
                     err_detail = "mount command timed out."
                 else:
                     err_detail = str(e)
                 self.installation_error = f"Failed to mount {device} at {full_mount_path}: {err_detail}"
                 print(f"ERROR: {self.installation_error}")
                 success = False
                 
            if not success:
                return False

        self._update_progress_text("Filesystems mounted successfully.", mount_progress_end)
        return True

    # ... rest of ProgressPage ... 