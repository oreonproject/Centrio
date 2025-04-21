from .. import backend

class ProgressPage(Gtk.Box):
    # // ... __init__, _update_progress_text, _attempt_unmount, _execute_storage_setup ...
    # // ... _configure_system, _create_user, _install_packages ...
    
    def _generate_fstab(self, config_data):
        \"\"\"Generates /etc/fstab using backend function.\"\"\"
        if self.stop_requested: return False, \"Stop requested\"
        disk_config = config_data.get('disk', {})
        
        # Only run if we actually created partitions automatically
        if disk_config.get(\"method\") != \"AUTOMATIC\" or not disk_config.get(\"partitions\"):
            print(\"Skipping fstab generation (Not automatic partitioning or no partition data).\")
            self._update_progress_text(\"fstab generation skipped.\", 0.85)
            return True 
            
        self._update_progress_text(\"Generating /etc/fstab...\", 0.85)
        
        success, err = backend.generate_fstab(
            self.target_root,
            disk_config,
            progress_callback=self._update_progress_text 
        )
        
        if success:
            self._update_progress_text(\"/etc/fstab generated.\", 0.88) # Small progress bump
        else:
             self.installation_error = err
             
        return success

    def _install_bootloader(self, config_data):
        # // ... existing bootloader logic ...
        # Update progress values slightly
        if not bootloader_config.get('install_bootloader', False):
            print(\"Skipping bootloader installation.\")
            self._update_progress_text(\"Bootloader installation skipped.\", 0.92) # Adjusted progress
            return True
        # // ... find primary_disk ...
        if not primary_disk:
             self.installation_error = \"Cannot determine target disk for bootloader installation.\"
             return False

        self._update_progress_text(\"Installing bootloader...\", 0.92) # Adjusted progress
        
        success, err = backend.install_bootloader_in_container(
            self.target_root, 
            primary_disk, 
            progress_callback=self._update_progress_text
        )
        
        if success:
            self._update_progress_text(\"Bootloader installed.\", 0.95) # Keep final progress
        else:
            self.installation_error = err
            
        return success
        
    # --- Main Installation Flow --- 

    def start_installation(self, main_window, config_data):
        # // ... existing start_installation setup ...
        thread = threading.Thread(target=self._run_installation_steps, args=(config_data,))
        thread.daemon = True 
        thread.start()

    def _run_installation_steps(self, config_data):
        \"\"\"Worker function to run installation steps sequentially.\"\"\"
        # Add _generate_fstab to the steps list
        steps = [
            (self._execute_storage_setup, config_data.get('disk', {})), # 0.0 - 0.35
            (self._configure_system, config_data),                   # 0.4 - 0.45
            (self._create_user, config_data),                        # 0.5 - 0.55
            (self._install_packages, config_data),                   # 0.6 - 0.8
            (self._generate_fstab, config_data),                     # 0.85 - 0.88 (New)
            (self._install_bootloader, config_data),                 # 0.92 - 0.95 (Adjusted)
            # Add post-install step here if needed
        ]

        success = True
        # // ... existing loop and finalize_ui ...
        for func, data in steps:
            if self.stop_requested:
                print(\"Installation stopped by user request.\")
                success = False
                # Don't set installation_error if stopped by user
                break
            
            step_success = func(data) 
            if not step_success:
                success = False
                if not self.installation_error:
                     self.installation_error = f\"Step {func.__name__} failed without error message.\"
                break
        
        def finalize_ui():
            if success and not self.stop_requested:
                final_message = \"Installation finished successfully!\"
                self._update_progress_text(final_message, 1.0)
                GLib.timeout_add(1500, self.main_window.navigate_to_page, \"finished\")
            elif self.stop_requested:
                 self._update_progress_text(\"Installation stopped.\", self.progress_bar.get_fraction())
                 self._attempt_unmount() # Attempt cleanup
            else:
                error_msg = f\"Installation failed: {self.installation_error}\"
                self._update_progress_text(error_msg, self.progress_bar.get_fraction())
                self._attempt_unmount() # Attempt cleanup
        
        GLib.idle_add(finalize_ui)

    def stop_installation(self):
        # // ... existing stop_installation ...
        print(\"Stop installation requested.\")
        if not self.stop_requested:
            self.stop_requested = True
            self._attempt_unmount() 