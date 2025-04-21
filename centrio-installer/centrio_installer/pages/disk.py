# centrio_installer/pages/disk.py
# // ... imports, format_bytes, command generation functions ...

class DiskPage(BaseConfigurationPage):
    def __init__(self, main_window, overlay_widget, **kwargs):
        # // ... super().__init__, state vars ...
        
        # // ... Info Label, Scan Button ...
        
        # // ... Disk List Group ...

        # --- Partitioning Options (Initially Hidden) ---
        self.part_group = Adw.PreferencesGroup(title=\"Storage Configuration\")
        self.part_group.set_description(\"Choose a partitioning method.\")
        self.part_group.set_visible(False) # Hide until scan is complete
        self.add(self.part_group)
        
        # Radio buttons for partitioning method
        self.auto_part_check = Gtk.CheckButton(label=\"Automatic Partitioning\")
        self.auto_part_check.set_tooltip_text(\"Erase selected disk(s) and use a default layout (Requires UEFI).\")
        # Enable Manual Partitioning Option
        self.manual_part_check = Gtk.CheckButton(label=\"Manual Partitioning (Use Existing)\", group=self.auto_part_check)
        self.manual_part_check.set_tooltip_text(\"Use partitions you created beforehand with another tool (e.g., GParted).\")
        self.manual_part_check.set_sensitive(True) # Enable manual option
        
        self.auto_part_check.connect(\"toggled\", self.on_partitioning_method_toggled)
        self.manual_part_check.connect(\"toggled\", self.on_partitioning_method_toggled) # Connect signal
        
        part_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        part_box.append(self.auto_part_check)
        part_box.append(self.manual_part_check)
        self.part_group.add(part_box)
        
        # Add info label for manual partitioning guidance
        self.manual_info_label = Gtk.Label(label=\"Select \'Manual\' if you have already created partitions (e.g., /, /boot/efi) using another tool before running this installer. The installer will attempt to find and use them.\")
        self.manual_info_label.set_wrap(True)
        self.manual_info_label.set_margin_top(6)
        self.manual_info_label.set_visible(False) # Show only when manual is selected
        part_box.append(self.manual_info_label)

        # // ... Confirmation Button ...
            
    # // ... connect_and_fetch_data, scan_for_disks, update_disk_list_ui, on_disk_toggled ...

    def on_partitioning_method_toggled(self, button):
         \"\"\"Handle radio button selection for partitioning method.\"\"\"
         # Update state based on which button is active
         if self.auto_part_check.get_active():
             print(\"Partitioning method: AUTOMATIC\")
             self.partitioning_method = \"AUTOMATIC\"
             self.manual_info_label.set_visible(False)
         elif self.manual_part_check.get_active():
             print(\"Partitioning method: MANUAL\")
             self.partitioning_method = \"MANUAL\"
             self.manual_info_label.set_visible(True) # Show guidance label
         else:
             self.partitioning_method = None
             self.manual_info_label.set_visible(False)
             
         self.update_complete_button_state()

    # // ... update_complete_button_state ...
        
    def apply_settings_and_return(self, button):
        \"\"\"Confirms storage plan, generates commands or detects partitions, stores config, and returns.\"\"\"
        # // ... validation checks ...
        if not self.complete_button.get_sensitive():
             # ... toast messages ...
             return

        print(f\"--- Confirming Storage Plan ---\")
        print(f\"  Selected Disks: {list(self.selected_disks)}\")
        print(f\"  Partitioning Method: {self.partitioning_method}\")
        
        config_values = {
            \"method\": self.partitioning_method,
            \"target_disks\": sorted(list(self.selected_disks)), 
            \"commands\": [], 
            \"partitions\": [] # Store detected/planned partitions here
        }

        if self.partitioning_method == \"AUTOMATIC\":
            # // ... existing automatic command generation ...
            primary_disk = sorted(list(self.selected_disks))[0]
            print(f\"  Generating AUTOMATIC partitioning commands for: {primary_disk}\")
            partition_prefix = \"p\" if \"nvme\" in primary_disk else \"\"
            wipe_cmd = generate_wipefs_command(primary_disk)
            parted_cmds = generate_gpt_commands(primary_disk)
            mkfs_cmds = generate_mkfs_commands(primary_disk, partition_prefix)
            all_commands = [wipe_cmd] + parted_cmds + mkfs_cmds
            config_values[\"commands\"] = all_commands 
            part1_suffix = f\"{partition_prefix}1\"
            part2_suffix = f\"{partition_prefix}2\"
            config_values[\"partitions\"] = [
                {\"device\": f\"{primary_disk}{part1_suffix}\", \"mountpoint\": \"/boot/efi\", \"fstype\": \"vfat\"},
                {\"device\": f\"{primary_disk}{part2_suffix}\", \"mountpoint\": \"/\", \"fstype\": \"ext4\"}
            ]
            print(f\"  Generated {len(all_commands)} commands for automatic partitioning.\")
                 
        elif self.partitioning_method == \"MANUAL\":
            print(\"  Processing MANUAL partitioning plan...\")
            # Scan selected disks for existing partitions
            detected_partitions = []
            primary_disk_path = sorted(list(self.selected_disks))[0] # Assume first disk primarily
            try:
                cmd = [\"lsblk\", \"-J\", \"-b\", \"-o\", \"NAME,SIZE,FSTYPE,TYPE,PKNAME,PATH\", primary_disk_path]
                # Run directly, not via pkexec needed for lsblk usually
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
                lsblk_data = json.loads(result.stdout)
                
                if \"blockdevices\" in lsblk_data:
                    for device in lsblk_data[\"blockdevices\"]:
                        # Find the main disk entry
                        if device.get(\"path\") == primary_disk_path and device.get(\"children\"):
                             # Iterate through partitions (children)
                             largest_part = None
                             largest_size = 0
                             efi_part = None
                             for part in device[\"children\"]:
                                 if part.get(\"type\") == \"part\":
                                     part_path = part.get(\"path\")
                                     part_fstype = part.get(\"fstype\")
                                     part_size = part.get(\"size\") or 0
                                     
                                     if not part_path:
                                         continue # Skip if no path
                                         
                                     # Identify potential EFI partition
                                     if part_fstype == \"vfat\" and part_size > 50*1024*1024 and part_size < 1024*1024*1024:
                                          efi_part = {\"device\": part_path, \"mountpoint\": \"/boot/efi\", \"fstype\": \"vfat\"}
                                          print(f\"    Found potential EFI partition: {part_path}\")
                                          
                                     # Track largest partition (likely root /)
                                     if part_size > largest_size and part_fstype and part_fstype != \"vfat\":
                                          largest_size = part_size
                                          largest_part = {\"device\": part_path, \"mountpoint\": \"/\", \"fstype\": part_fstype}
                                          print(f\"    Found potential root partition: {part_path} ({part_fstype})\")
                                          
                             # Add detected EFI and root partitions to config
                             if efi_part:
                                 detected_partitions.append(efi_part)
                             if largest_part:
                                 detected_partitions.append(largest_part)
                             else:
                                 # If no non-EFI partition found, maybe raise error or warn?
                                 print(\"Warning: Could not identify a suitable root partition on the manually partitioned disk.\")
                                 # We need at least a root partition
                                 if not any(p[\'mountpoint\'] == \'/\' for p in detected_partitions):
                                     self.show_toast(\"Manual Partitioning Error: Could not find a suitable root partition. Please create one.\")
                                     return
                
                config_values[\"partitions\"] = detected_partitions
                config_values[\"commands\"] = [] # Ensure no partitioning commands run
                
                if not detected_partitions:
                     self.show_toast(\"Manual Partitioning Error: No suitable partitions found on selected disk.\")
                     return

            except Exception as e:
                print(f\"ERROR scanning for manual partitions: {e}\")
                self.show_toast(f\"Error detecting manual partitions: {e}\")
                return

        # Show confirmation toast
        if self.partitioning_method == \"AUTOMATIC\":
            self.show_toast(f\"Storage plan confirmed (Automatic). Commands generated.\")
        elif self.partitioning_method == \"MANUAL\":
             if config_values[\"partitions\"]:
                  self.show_toast(f\"Storage plan confirmed (Manual). Found partitions to use.\")
             else:
                  # Should have returned earlier if no partitions found
                  self.show_toast(\"Storage plan confirmed (Manual), but partition detection failed.\")
        else:
             self.show_toast(f\"Storage plan confirmed ({self.partitioning_method}).\")
            
        super().mark_complete_and_return(button, config_values=config_values)
        
    # // ... rest of DiskPage ... 