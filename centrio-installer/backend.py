# centrio_installer/backend.py

import subprocess
import shlex
import os
import re # For parsing os-release
from .utils import get_os_release_info
import errno # For checking mount errors
import time   # For delays

def _run_command(command_list, description, progress_callback=None, timeout=None, pipe_input=None):
    """Runs a command, using pkexec if not already root, captures output, handles errors.
    
    Checks os.geteuid() to determine if running as root.
    """
    
    is_root = os.geteuid() == 0
    final_command_list = []
    execution_method = ""

    if is_root:
        final_command_list = command_list
        execution_method = "directly as root"
        print(f"Executing Backend Step ({execution_method}): {description} -> {' '.join(shlex.quote(c) for c in final_command_list)}")
    else:
        # Prepend pkexec if not running as root
        final_command_list = ["pkexec"] + command_list
        execution_method = "via pkexec"
        cmd_str = ' '.join(shlex.quote(c) for c in final_command_list)
        print(f"Executing Backend Step ({execution_method}): {description} -> {cmd_str}")
        if progress_callback:
            progress_callback(f"Requesting privileges for: {description}...")
        
    stderr_output = ""
    stdout_output = ""
    try:
        # Run the command (either directly or with pkexec)
        process = subprocess.Popen(
            final_command_list, # Use the decided command list
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if pipe_input is not None else None,
            text=True
        )
        
        stdout_output, stderr_output = process.communicate(input=pipe_input, timeout=timeout)
        
        print(f"  Command {description} stdout:\n{stdout_output.strip()}")
        if stderr_output:
             # Filter pkexec messages only if running via pkexec
             filtered_stderr = stderr_output
             if execution_method == "via pkexec":
                  filtered_stderr = "\n".join(line for line in stderr_output.splitlines() if "using backend" not in line)
             
             if filtered_stderr.strip():
                 print(f"  Command {description} stderr:\n{filtered_stderr.strip()}")

        if process.returncode != 0:
            error_detail = stderr_output.strip() or f"Exited with code {process.returncode}"
            # Check for pkexec/PolicyKit errors only if running via pkexec
            error_msg = f"{description} failed ({execution_method}): {error_detail}"
            if execution_method == "via pkexec":
                if "Authentication failed" in error_detail or process.returncode == 127:
                     error_msg = f"Authorization failed for {description}. Check PolicyKit rules or password."
                elif "Cannot run program" in error_detail or process.returncode == 126:
                     error_msg = f"Command not found or not permitted by PolicyKit for {description}: {command_list[0]}"
                # else: use the generic error_msg already set
            
            print(f"ERROR: {error_msg}")
            
            # --- Add dmesg logging on error --- 
            print("--- Attempting to get last kernel messages (dmesg) ---")
            try:
                 # Run dmesg directly, not via _run_command to avoid loops/pkexec issues
                 # Get last 50 lines with timestamps
                 dmesg_cmd = ["dmesg", "-T"] 
                 dmesg_process = subprocess.run(dmesg_cmd, capture_output=True, text=True, check=False, timeout=5)
                 if dmesg_process.stdout:
                      # Use tail command for potentially large output (more reliable than split/slice)
                      tail_process = subprocess.Popen(["tail", "-n", "50"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                      dmesg_tail_stdout, _ = tail_process.communicate(input=dmesg_process.stdout)
                      print(f"Last 50 lines of dmesg:\n{dmesg_tail_stdout.strip()}")
                 else:
                      print("Could not capture dmesg output.")
                 if dmesg_process.stderr:
                      print(f"dmesg stderr: {dmesg_process.stderr.strip()}")
            except FileNotFoundError:
                 print("dmesg or tail command not found.")
            except Exception as dmesg_e:
                 print(f"Failed to run or capture dmesg: {dmesg_e}")
            print("-----------------------------------------------------")
            # --- End dmesg logging --- 
            
            return False, error_msg, stdout_output.strip() 
            
        print(f"SUCCESS: {description} completed ({execution_method}).")
        return True, "", stdout_output.strip()

    except FileNotFoundError:
        # Handle command-not-found specifically
        cmd_not_found = final_command_list[0]
        err = f"Command not found: {cmd_not_found}. Ensure it's installed and in the PATH."
        if execution_method == "via pkexec" and cmd_not_found == "pkexec":
            err = "Command not found: pkexec. Cannot run privileged commands."
        print(f"ERROR: {err}")
        return False, err, None 
    except subprocess.TimeoutExpired:
        err = f"Timeout expired after {timeout}s for {description} ({execution_method})."
        try:
            process.kill()
            process.wait()
        except Exception as kill_e:
            print(f"Warning: Error trying to kill timed out process: {kill_e}")
        return False, err, stdout_output.strip() 
    except Exception as e:
        err_detail = stderr_output.strip() or str(e)
        err = f"Unexpected error during {description} ({execution_method}): {err_detail}"
        print(f"ERROR: {err}")
        return False, err, stdout_output.strip()

# --- New _run_in_chroot function ---
def _run_in_chroot(target_root, command_list, description, progress_callback=None, timeout=None, pipe_input=None):
    """Runs a command inside the target root using chroot, managing bind mounts.
    
    Requires manual mounting/unmounting of /proc, /sys, /dev, /dev/pts, and /etc/resolv.conf.
    Assumes the caller (_run_command) handles root privileges.
    """
    host_dbus_socket = "/run/dbus/system_bus_socket"
    target_dbus_socket = os.path.join(target_root, host_dbus_socket.lstrip('/'))
    
    mount_points = {
        "proc": os.path.join(target_root, "proc"),
        "sys": os.path.join(target_root, "sys"),
        "dev": os.path.join(target_root, "dev"),
        "dev/pts": os.path.join(target_root, "dev/pts"),
        "resolv.conf": os.path.join(target_root, "etc/resolv.conf"),
        "dbus": target_dbus_socket # Add dbus socket target
    }
    mounted_paths = set()
    
    try:
        # --- Mount API filesystems, resolv.conf, and D-Bus socket --- 
        print(f"Setting up chroot environment in {target_root}...")
        
        # Prepare target directories/files first
        resolv_conf_target = mount_points["resolv.conf"]
        resolv_conf_dir = os.path.dirname(resolv_conf_target)
        if not os.path.exists(resolv_conf_dir):
             # Ensure target /etc directory exists
             try:
                 print(f"  Creating directory {resolv_conf_dir}...")
                 os.makedirs(resolv_conf_dir, exist_ok=True)
             except OSError as e:
                 raise RuntimeError(f"Failed to create target directory {resolv_conf_dir}: {e}") from e
                 
        # Ensure target /etc/resolv.conf file exists for bind mount
        if not os.path.exists(resolv_conf_target):
            try:
                 print(f"  Creating empty file {resolv_conf_target} for bind mount...")
                 # Use 'w' to create if it doesn't exist, then close immediately.
                 open(resolv_conf_target, 'w').close()
                 # Optionally set permissions? Might not be necessary.
            except OSError as e:
                 raise RuntimeError(f"Failed to create target file {resolv_conf_target}: {e}") from e
                 
        if os.path.exists(host_dbus_socket):
             dbus_target_dir = os.path.dirname(mount_points["dbus"])
             try:
                 os.makedirs(dbus_target_dir, exist_ok=True)
                 # Create an empty file for the socket bind mount target?
                 # Or maybe just mount the socket file directly? Mount requires dir for source/target usually?
                 # Let's try mounting the socket file directly using --bind.
             except OSError as e:
                 raise RuntimeError(f"Failed to prepare target D-Bus directory {dbus_target_dir}: {e}") from e
        else:
             print(f"Warning: Host D-Bus socket {host_dbus_socket} not found. Services inside chroot might fail.")

        mount_commands = [
            ("proc",    "proc",                mount_points["proc"],                 ["-t", "proc", "nodev,noexec,nosuid"]), 
            ("sysfs",   "sys",                 mount_points["sys"],                  ["-t", "sysfs", "nodev,noexec,nosuid"]), 
            ("devtmpfs","udev",               mount_points["dev"],                  ["-t", "devtmpfs", "mode=0755,nosuid"]), 
            ("devpts",  "devpts",              mount_points["dev/pts"],              ["-t", "devpts", "mode=0620,gid=5,nosuid,noexec"]), 
            ("bind",    "/etc/resolv.conf",    mount_points["resolv.conf"],         ["--bind"]),
            # Add D-Bus socket mount if host socket exists
            ("bind",    host_dbus_socket,      mount_points["dbus"],               ["--bind"])
        ]

        for name, source, target, options in mount_commands:
            # Skip D-Bus mount if source doesn't exist
            if name == "bind" and source == host_dbus_socket and not os.path.exists(host_dbus_socket):
                 print(f"  Skipping D-Bus socket mount (source {host_dbus_socket} not found).")
                 continue
                 
            try:
                # Ensure target dir exists for non-file bind mounts
                if name != "bind" or source != host_dbus_socket:
                     os.makedirs(target, exist_ok=True)
                # For the dbus socket bind mount, the target *file* path was created above
                # We just need the directory for it.
                elif name == "bind" and source == host_dbus_socket:
                     os.makedirs(os.path.dirname(target), exist_ok=True)
                     # Create empty file as mount target if it doesn't exist? Bind mount needs a target.
                     if not os.path.exists(target):
                         open(target, 'a').close() 
                          
                mount_cmd = ["mount"] + options + [source, target]
                print(f"  Mounting {source} -> {target} ({name})")
                result = subprocess.run(mount_cmd, check=True, capture_output=True, text=True, timeout=15)
                mounted_paths.add(target)
            except FileNotFoundError:
                 raise RuntimeError("Mount command failed: 'mount' executable not found.")
            except subprocess.CalledProcessError as e:
                # Check if already mounted (exit code 32 often means this)
                if e.returncode == 32 and ("already mounted" in e.stderr or "mount point does not exist" in e.stderr or "Not a directory" in e.stderr): # Added check for dbus socket
                    print(f"    Warning: Mount for {target} possibly already exists or target invalid? {e.stderr.strip()}")
                    mounted_paths.add(target) 
                else:
                    raise RuntimeError(f"Failed to mount {source} to {target}: {e.stderr.strip()}") from e
            except Exception as e:
                 raise RuntimeError(f"Unexpected error mounting {source}: {e}") from e

        # --- Execute command in chroot --- 
        chroot_cmd = ["chroot", target_root] + command_list
        # Use _run_command to handle execution (it checks root/pkexec itself)
        success, err, stdout = _run_command(chroot_cmd, description, progress_callback, timeout, pipe_input)
        return success, err, stdout
        
    finally:
        # --- Unmount everything in reverse order --- 
        print(f"Cleaning up chroot environment in {target_root}...")
        # Sync before attempting unmounts
        try: subprocess.run(["sync"], check=False, timeout=5) 
        except Exception: pass
        
        for target in sorted(list(mounted_paths), reverse=True):
            print(f"  Unmounting {target}...")
            umount_cmd = ["umount", target]
            try:
                 # Sync before each unmount attempt
                 try: subprocess.run(["sync"], check=False, timeout=5) 
                 except Exception: pass
                 
                 # Try normal unmount first
                 subprocess.run(umount_cmd, check=True, capture_output=True, text=True, timeout=15) 
                 print(f"    Successfully unmounted {target}")
            except subprocess.CalledProcessError as e_norm:
                 print(f"    Warning: Normal unmount failed for {target}: {e_norm.stderr.strip()}. Trying lazy unmount...")
                 # Sync before lazy unmount
                 try: subprocess.run(["sync"], check=False, timeout=5) 
                 except Exception: pass
                 umount_lazy_cmd = ["umount", "-l", target]
                 try:
                      subprocess.run(umount_lazy_cmd, check=True, capture_output=True, text=True, timeout=10)
                      print(f"      Lazy unmount successful for {target}")
                 except Exception as e_lazy:
                      print(f"      Warning: Lazy unmount also failed for {target}: {e_lazy}")
            except Exception as e:
                 print(f"    Warning: Error during unmount of {target}: {e}")
        
        # Final sync
        try: subprocess.run(["sync"], check=False, timeout=5) 
        except Exception: pass

# --- Configuration Functions ---

def configure_system_in_container(target_root, config_data, progress_callback=None):
    """Configures timezone, locale, keyboard, hostname in target via chroot."""
    
    # Timezone
    tz = config_data.get('timedate', {}).get('timezone')
    if tz:
        success, err, _ = _run_in_chroot(target_root, ["timedatectl", "set-timezone", tz], "Set Timezone", progress_callback, timeout=15)
        if not success: return False, err
    else:
        print("Skipping timezone configuration (not provided).")

    # Locale
    locale = config_data.get('language', {}).get('locale')
    if locale:
        success, err, _ = _run_in_chroot(target_root, ["localectl", "set-locale", f"LANG={locale}"], "Set Locale", progress_callback, timeout=15)
        if not success: return False, err
    else:
         print("Skipping locale configuration (not provided).")

    # Keymap
    keymap = config_data.get('keyboard', {}).get('layout')
    if keymap:
        success, err, _ = _run_in_chroot(target_root, ["localectl", "set-keymap", keymap], "Set Keymap", progress_callback, timeout=15)
        if not success: return False, err
    else:
        print("Skipping keymap configuration (not provided).")
        
    # Hostname
    hostname = config_data.get('network', {}).get('hostname')
    if hostname:
        success, err, _ = _run_in_chroot(target_root, ["hostnamectl", "set-hostname", hostname], "Set Hostname", progress_callback, timeout=15)
        if not success: return False, err
    else:
        print("Skipping hostname configuration (not provided).")

    return True, ""

def create_user_in_container(target_root, user_config, progress_callback=None):
    """Creates user account in target via chroot."""
    username = user_config.get('username')
    password = user_config.get('password', None) # Get password from config
    is_admin = user_config.get('is_admin', False)
    real_name = user_config.get('real_name', '') 
    
    if not username:
        return False, "Username not provided in user configuration.", None
    # Allow proceeding even if password is None or empty, chpasswd might handle it or fail later
    # if not password:
    #      return False, "Password not provided for user creation.", None

    # Build useradd command
    useradd_cmd = ["useradd", "-m", "-s", "/bin/bash", "-U"]
    if real_name:
        useradd_cmd.extend(["-c", real_name])
    if is_admin:
        useradd_cmd.extend(["-G", "wheel"]) # Add to wheel group for sudo
    useradd_cmd.append(username)
    
    success, err, _ = _run_in_chroot(target_root, useradd_cmd, f"Create User {username}", progress_callback, timeout=30)
    if not success: return False, err, None
    
    # Set password using chpasswd - only if password was provided
    if password is not None: # Check if password exists (even if empty string, let chpasswd decide)
        chpasswd_input = f"{username}:{password}"
        success, err, _ = _run_in_chroot(target_root, ["chpasswd"], f"Set Password for {username}", progress_callback, timeout=15, pipe_input=chpasswd_input)
        if not success: 
            print(f"Warning: Failed to set password for {username} after user creation: {err}")
            # Decide if this should be a fatal error for the whole installation
            # return False, err, None # Stop installation if password set fails?
            pass # Continue for now
    else:
         print(f"Warning: No password provided for user {username}. Account created without password set.")
        
    return True, "", None

# --- Package Installation ---

def install_packages_dnf(target_root, progress_callback=None):
    """Installs base packages using DNF --installroot, parsing output for progress.
    
    Note: This function bypasses _run_command and assumes it is run with root privileges.
    It directly calls subprocess.Popen for DNF.
    """
    
    # --- Root Check --- 
    if os.geteuid() != 0:
        err = "install_packages_dnf must be run as root."
        print(f"ERROR: {err}")
        return False, err

    # --- Get Release Version --- 
    os_info = get_os_release_info()
    releasever = os_info.get("VERSION_ID")
    if not releasever:
        print("Warning: Could not detect OS VERSION_ID. Falling back to default.")
        # Attempt to get from target_root if possible? Requires parsing /etc/os-release
        # For now, stick to fallback or error
        # return False, "Could not determine release version for DNF." # Option: fail hard
        releasever = "40" # Default fallback
    print(f"Using release version: {releasever}")
    
    # --- Define Packages and Command --- 
    packages = [
        "@core", "kernel", "grub2-efi-x64", "grub2-pc", "efibootmgr", 
        "linux-firmware", "NetworkManager", "systemd-resolved", 
        "bash-completion", "dnf-utils"
        # Add more packages as needed
    ]
    
    dnf_cmd = [
        "dnf", 
        "install", 
        "-y", 
        "--nogpgcheck", 
        f"--installroot={target_root}",
        f"--releasever={releasever}",
        f"--setopt=install_weak_deps=False"
    ] + packages

    print(f"Executing Backend Step (directly as root): Install Base Packages (DNF) -> {' '.join(shlex.quote(c) for c in dnf_cmd)}")
    if progress_callback:
        progress_callback("Starting DNF package installation (This may take a while...)", 0.0) # Initial message
        
    # --- Execute DNF and Stream Output --- 
    process = None
    stderr_output = ""
    try:
        process = subprocess.Popen(
            dnf_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1 # Line-buffered
        )

        # Regex patterns for progress parsing
        # Example: Downloading Packages: [ 15%] |           | 112 kB/s | 761 kB | 00m06s ETA
        download_progress_re = re.compile(r"^Downloading Packages:.*?\[\s*(\d+)%\]")
        # Example: Installing        : kernel-core-6.9.5-200.fc40.x86_64        163/170 
        install_progress_re = re.compile(r"^(Installing|Updating|Upgrading|Cleanup|Verifying)\s*:.*?\s+(\d+)/(\d+)\s*$")
        # Corrected regex: removed extra backslash before d+
        total_packages_re = re.compile(r"Total download size:.*Installed size:.* Package count: (\d+)") # May not always appear

        total_packages = 0
        packages_processed = 0
        current_phase = "Initializing"
        last_fraction = 0.0
        
        # Read stdout line by line
        for line in iter(process.stdout.readline, ''):
            line_strip = line.strip()
            if not line_strip: continue
            # print(f"DNF_RAW: {line_strip}") # Debug: print raw DNF output
            
            # --- Phase Detection (simple) --- 
            if "Downloading Packages" in line_strip: current_phase = "Downloading"
            elif "Running transaction check" in line_strip: current_phase = "Checking Transaction"
            elif "Running transaction test" in line_strip: current_phase = "Testing Transaction"
            elif "Running transaction" in line_strip: current_phase = "Running Transaction"
            elif line_strip.startswith("Installing") or line_strip.startswith("Updating"): current_phase = "Installing"
            elif line_strip.startswith("Running scriptlet"): current_phase = "Running Scriptlets"
            elif line_strip.startswith("Verifying"): current_phase = "Verifying"
            elif line_strip.startswith("Installed:"): current_phase = "Finalizing Installation"
            elif line_strip.startswith("Complete!"): current_phase = "Complete"

            # --- Progress Parsing --- 
            fraction = last_fraction # Default to last known fraction
            message = f"DNF: {current_phase}..."
            
            # Total Package Count (Best effort)
            match_total = total_packages_re.search(line_strip)
            if match_total:
                 total_packages = int(match_total.group(1))
                 print(f"Detected total package count: {total_packages}")

            # Download Progress
            match_dl = download_progress_re.search(line_strip)
            if match_dl:
                 download_percent = int(match_dl.group(1))
                 # Estimate overall progress: Assume download is first 30%?
                 fraction = 0.0 + (download_percent / 100.0) * 0.30
                 message = f"DNF: Downloading ({download_percent}%)..."
                 
            # Installation/Verification Progress
            match_install = install_progress_re.search(line_strip)
            if match_install:
                current_phase = match_install.group(1) # More specific phase
                packages_processed = int(match_install.group(2))
                total_packages_from_line = int(match_install.group(3))
                # Use total from line if greater than previously detected (more reliable)
                if total_packages_from_line > total_packages:
                    total_packages = total_packages_from_line
                
                if total_packages > 0:
                    # Estimate overall progress: Assume install/verify is 30% to 95%?
                    phase_progress = packages_processed / total_packages
                    if current_phase == "Installing" or current_phase == "Updating" or current_phase == "Upgrading":
                       fraction = 0.30 + phase_progress * 0.60 # Installation: 30% -> 90%
                    elif current_phase == "Verifying":
                       fraction = 0.90 + phase_progress * 0.05 # Verification: 90% -> 95%
                    elif current_phase == "Cleanup":
                       fraction = 0.95 + phase_progress * 0.05 # Cleanup: 95% -> 100%
                    message = f"DNF: {current_phase} ({packages_processed}/{total_packages})..."
                else:
                     message = f"DNF: {current_phase} (package {packages_processed})..."
                     fraction = 0.30 # Fallback if total not found yet

            # Clamp fraction between 0.0 and 0.99 during processing
            fraction = max(0.0, min(fraction, 0.99))
            last_fraction = fraction
            
            if progress_callback:
                progress_callback(message, fraction)

            # Check if process exited prematurely
            if process.poll() is not None:
                print("Warning: DNF process exited while reading stdout.")
                break
        
        # --- Wait and Check Result --- 
        process.stdout.close() # Close stdout pipe
        return_code = process.wait(timeout=60) # Wait briefly for final exit
        stderr_output = process.stderr.read() # Read all stderr at the end
        process.stderr.close()
        
        if return_code != 0:
            error_msg = f"DNF installation failed (rc={return_code}). Stderr:\n{stderr_output.strip()}"
            print(f"ERROR: {error_msg}")
            if progress_callback: progress_callback(error_msg, last_fraction)
            
            # --- Add dmesg logging on error --- 
            print("--- Attempting to get last kernel messages (dmesg) ---")
            try:
                 # Run dmesg directly, not via _run_command to avoid loops/pkexec issues
                 dmesg_cmd = ["dmesg"] # Request last few lines might be better
                 dmesg_process = subprocess.run(dmesg_cmd, capture_output=True, text=True, check=False, timeout=5)
                 if dmesg_process.stdout:
                      last_lines = "\n".join(dmesg_process.stdout.strip().split('\n')[-20:]) # Get last 20 lines
                      print(f"Last ~20 lines of dmesg:\n{last_lines}")
                 else:
                      print("Could not capture dmesg output.")
                 if dmesg_process.stderr:
                      print(f"dmesg stderr: {dmesg_process.stderr.strip()}")
            except Exception as dmesg_e:
                 print(f"Failed to run or capture dmesg: {dmesg_e}")
            print("-----------------------------------------------------")
            # --- End dmesg logging --- 
            
            return False, error_msg
        else:
             print(f"SUCCESS: DNF installation completed.")
             if progress_callback: progress_callback("DNF installation complete.", 1.0)
             # Optionally enable NetworkManager here (but requires _run_in_chroot, which uses _run_command)
             # Consider moving NM enable to a separate step after this function returns success.
             return True, ""
            
    except FileNotFoundError:
        err = "Command not found: dnf. Cannot install packages."
        print(f"ERROR: {err}")
        if progress_callback: progress_callback(err, 0.0)
        return False, err
    except subprocess.TimeoutExpired:
        err = "Timeout expired during DNF execution."
        print(f"ERROR: {err}")
        if process: process.kill()
        if progress_callback: progress_callback(err, last_fraction)
        return False, err
    except Exception as e:
        err = f"Unexpected error during DNF execution: {e}\nStderr so far: {stderr_output}"
        print(f"ERROR: {err}")
        if process: process.kill()
        if progress_callback: progress_callback(err, last_fraction)
        return False, err
    finally:
         # Ensure streams are closed if process was started
         if process:
             if process.stdout and not process.stdout.closed: process.stdout.close()
             if process.stderr and not process.stderr.closed: process.stderr.close()

# --- Move NetworkManager Enable --- 
# We need a function that uses _run_in_chroot (and thus _run_command for root check)
def enable_network_manager(target_root, progress_callback=None):
    """Enables NetworkManager service in the target system via chroot."""
    if progress_callback:
        progress_callback("Enabling NetworkManager service...", 0.96) # Example fraction
    
    nm_enable_cmd = ["systemctl", "enable", "NetworkManager.service"]
    success, err, _ = _run_in_chroot(target_root, nm_enable_cmd, "Enable NetworkManager Service", progress_callback=None, timeout=30)
    if not success: 
        warning_msg = f"Warning: Failed to enable NetworkManager service: {err}"
        print(warning_msg)
        if progress_callback: progress_callback(warning_msg, 0.97) # Update UI with warning
        # Continue installation even if service enabling fails? Let's return True but log warning.
        return True, warning_msg # Indicate success overall, but pass warning
    else:
        print("Successfully enabled NetworkManager service.")
        if progress_callback: progress_callback("NetworkManager service enabled.", 0.97)
        return True, ""

# --- Bootloader Installation ---

def install_bootloader_in_container(target_root, primary_disk, progress_callback=None):
    """Installs GRUB2 bootloader via chroot."""
    
    # Detect if system is likely UEFI (check for /sys/firmware/efi)
    is_uefi = os.path.exists("/sys/firmware/efi")
    grub_target_disk = primary_disk # Install MBR/GPT stage 1 to disk
    
    if is_uefi:
        print("UEFI system detected, installing GRUB for EFI.")
        # Install GRUB EFI binaries and register with firmware
        # Assumes /boot/efi is mounted at target_root/boot/efi
        grub_install_cmd = [
            "grub2-install", 
            "--target=x86_64-efi",
            "--efi-directory=/boot/efi", # Relative to target_root inside container
            "--bootloader-id=Centrio",   # Boot menu entry name
            "--recheck"
            # No disk device needed for pure UEFI install
        ]
    else:
        print("BIOS system detected, installing GRUB for BIOS.")
        # Install GRUB BIOS boot sector
        grub_install_cmd = [
            "grub2-install", 
            "--target=i386-pc", 
            grub_target_disk # Install to the disk MBR/boot sector
        ]

    success, err, _ = _run_in_chroot(target_root, grub_install_cmd, "Install GRUB", progress_callback, timeout=120)
    if not success: return False, err, None
    
    # Generate GRUB config
    # Ensure /boot is mounted correctly within the container context
    grub_mkconfig_cmd = ["grub2-mkconfig", "-o", "/boot/grub2/grub.cfg"]
    success, err, _ = _run_in_chroot(target_root, grub_mkconfig_cmd, "Generate GRUB Config", progress_callback, timeout=120)
    if not success: return False, err, None

    return True, "", None 

# --- Service Management Helpers --- 
def _manage_service(action, service_name):
    """Helper to start or stop a systemd service."""
    if action not in ["start", "stop"]:
        return False, f"Invalid service action: {action}"
    
    cmd = ["systemctl", action, service_name]
    # Use _run_command, assumes root check handled there
    success, err, _ = _run_command(cmd, f"{action.capitalize()} service {service_name}")
    if not success:
         print(f"Warning: Failed to {action} service {service_name}: {err}")
         # Don't make this fatal? Might prevent cleanup.
         # return False, err 
    return success, err

def _stop_service(service_name):
    print(f"Attempting to stop service: {service_name}...")
    return _manage_service("stop", service_name)

def _start_service(service_name):
    print(f"Attempting to start service: {service_name}...")
    return _manage_service("start", service_name)

# --- LVM Deactivation Helper --- 
def _deactivate_lvm_on_disk(disk_device, progress_callback=None):
    """Attempts to find and deactivate LVM VGs associated with a disk and its partitions."""
    print(f"Checking for and deactivating LVM on {disk_device} and its partitions...")
    if progress_callback:
        progress_callback(f"Checking LVM on {disk_device}...", None) # Text only update

    devices_to_check = set([disk_device])
    vg_names_found = set()
    all_success = True
    errors = []

    # 1. Find partitions of the main disk
    try:
        lsblk_cmd = ["lsblk", "-n", "-o", "PATH", "--raw", disk_device]
        print(f"  Running: {' '.join(shlex.quote(c) for c in lsblk_cmd)}")
        lsblk_result = subprocess.run(lsblk_cmd, capture_output=True, text=True, check=False, timeout=10)
        if lsblk_result.returncode == 0:
            found_paths = [line.strip() for line in lsblk_result.stdout.split('\n') if line.strip() and line.strip() != disk_device]
            print(f"  Found potential partition paths via lsblk: {found_paths}")
            devices_to_check.update(found_paths)
        else:
            print(f"  Warning: lsblk failed for {disk_device} (rc={lsblk_result.returncode}), checking only base device for PVs.")
    except Exception as e:
        print(f"  Warning: Error running lsblk to find partitions for {disk_device}: {e}")
        # Continue with just the base disk_device

    # 2. Find VGs associated with each device (disk + partitions)
    print(f"  Checking devices for LVM PVs: {list(devices_to_check)}")
    for device in devices_to_check:
        try:
            pvs_cmd = ["pvs", "--noheadings", "-o", "vg_name", "--select", f"pv_name={device}"]
            # Use subprocess directly here as _run_command adds too much noise for non-errors
            print(f"    Checking PV on {device}...")
            result = subprocess.run(pvs_cmd, capture_output=True, text=True, check=False, timeout=10)
            
            if result.returncode == 0:
                vgs = set(line.strip() for line in result.stdout.splitlines() if line.strip())
                if vgs:
                     print(f"      Found VGs on {device}: {vgs}")
                     vg_names_found.update(vgs)
            elif "No physical volume found" in result.stderr or "No PVs found" in result.stdout:
                # This is expected if the device isn't an LVM PV
                pass
            else:
                 # Real error running pvs
                 err_msg = f"Failed to run pvs for {device}: {result.stderr.strip()}"
                 print(f"    Warning: {err_msg}")
                 errors.append(err_msg)
                 all_success = False # Mark as potentially incomplete
                 
        except Exception as e:
             err_msg = f"Unexpected error checking PV on {device}: {e}"
             print(f"    ERROR: {err_msg}")
             errors.append(err_msg)
             all_success = False
             
    if not vg_names_found:
         print(f"  No LVM Volume Groups found associated with {disk_device} or its partitions.")
         return True, "" # Not an error if no VGs found

    # 3. Deactivate all found VGs
    print(f"  Found unique LVM VGs to deactivate: {vg_names_found}. Attempting deactivation...")
    for vg_name in vg_names_found:
         vgchange_cmd = ["vgchange", "-an", vg_name]
         # Use _run_command here as deactivation failure is important
         vg_success, vg_err, _ = _run_command(vgchange_cmd, f"Deactivate VG {vg_name}")
         if not vg_success:
             print(f"    Warning: Failed to deactivate VG {vg_name}: {vg_err}")
             errors.append(f"Failed to deactivate VG {vg_name}: {vg_err}")
             all_success = False
         else:
              print(f"    Successfully deactivated VG {vg_name}.")
              time.sleep(0.5) # Small delay after deactivation
              
    if progress_callback:
         status = "Deactivation complete." if all_success and not errors else "Deactivation attempted, some errors occurred."
         progress_callback(f"LVM Check on {disk_device}: {status}", None)
         
    final_error_str = "\n".join(errors)
    return all_success, final_error_str

# --- Device Mapper Removal Helper --- 
def _remove_dm_mappings(disk_device, progress_callback=None):
    """Attempts to find and remove device-mapper mappings for LVM LVs on a disk."""
    print(f"Checking for and removing LVM device-mapper mappings associated with {disk_device}...")
    if progress_callback:
        progress_callback(f"Removing DM mappings for {disk_device}...", None)

    devices_to_check = set([disk_device])
    vg_names_found = set()
    lvs_to_remove = set() # Store LV paths like /dev/vg/lv or /dev/mapper/vg-lv
    all_success = True
    errors = []

    # 1. Find partitions (same logic as _deactivate_lvm_on_disk)
    try:
        lsblk_cmd = ["lsblk", "-n", "-o", "PATH", "--raw", disk_device]
        lsblk_result = subprocess.run(lsblk_cmd, capture_output=True, text=True, check=False, timeout=10)
        if lsblk_result.returncode == 0:
            devices_to_check.update([p.strip() for p in lsblk_result.stdout.split('\n') if p.strip()])
    except Exception:
        pass # Ignore errors, just use base disk device

    # 2. Find VGs associated with each device
    for device in devices_to_check:
        try:
            pvs_cmd = ["pvs", "--noheadings", "-o", "vg_name", "--select", f"pv_name={device}"]
            result = subprocess.run(pvs_cmd, capture_output=True, text=True, check=False, timeout=10)
            if result.returncode == 0:
                vg_names_found.update(line.strip() for line in result.stdout.splitlines() if line.strip())
        except Exception as e:
            errors.append(f"Error finding VGs on {device}: {e}")
            all_success = False
            
    if not vg_names_found:
         print(f"  No LVM Volume Groups found for {disk_device}, skipping dmsetup removal.")
         return True, ""

    # 3. Find LVs within those VGs
    print(f"  Found VGs: {vg_names_found}. Checking for associated LVs...")
    for vg_name in vg_names_found:
        try:
             # Get LV paths, prefer /dev/mapper/ format if possible, else /dev/vg/lv
             lvs_cmd = ["lvs", "--noheadings", "-o", "lv_path", vg_name]
             result = subprocess.run(lvs_cmd, capture_output=True, text=True, check=False, timeout=10)
             if result.returncode == 0:
                 lv_paths = set(line.strip() for line in result.stdout.splitlines() if line.strip())
                 if lv_paths:
                      print(f"    Found LVs in VG {vg_name}: {lv_paths}")
                      lvs_to_remove.update(lv_paths)
             else:
                 err_msg = f"Failed to list LVs for VG {vg_name}: {result.stderr.strip()}"
                 print(f"    Warning: {err_msg}")
                 errors.append(err_msg)
                 all_success = False
        except Exception as e:
             err_msg = f"Unexpected error listing LVs for VG {vg_name}: {e}"
             print(f"    ERROR: {err_msg}")
             errors.append(err_msg)
             all_success = False
             
    if not lvs_to_remove:
        print(f"  No active LVs found in VGs {vg_names_found}.")
        return True, "\n".join(errors) # Return success even if LVs couldn't be listed, but include errors

    # 4. Remove DM mappings for found LVs
    print(f"  Attempting to remove DM mappings for LVs: {lvs_to_remove}")
    for lv_path in lvs_to_remove:
        # Need the mapper name (e.g., vg--name-lv--name) which might differ from lv_path (/dev/vg_name/lv_name)
        # We can try removing both common forms: /dev/mapper/vg-lv and the lv_path directly
        # dmsetup usually works with the name in /dev/mapper
        mapper_name = os.path.basename(lv_path)
        # Attempt removal using the basename (common case)
        dmsetup_cmd = ["dmsetup", "remove", mapper_name]
        dm_success, dm_err, _ = _run_command(dmsetup_cmd, f"Remove DM mapping {mapper_name}")
        
        if dm_success:
            print(f"    Successfully removed DM mapping {mapper_name}.")
            time.sleep(0.5) # Small delay
        else:
            # If basename fails, try the full path (less common for dmsetup remove)
            if "No such device or address" not in dm_err:
                print(f"    Attempting removal using full path {lv_path}...")
                dmsetup_cmd_fullpath = ["dmsetup", "remove", lv_path]
                dm_success_fp, dm_err_fp, _ = _run_command(dmsetup_cmd_fullpath, f"Remove DM mapping {lv_path}")
                if dm_success_fp:
                     print(f"    Successfully removed DM mapping using full path {lv_path}.")
                     time.sleep(0.5) # Small delay
                elif "No such device or address" not in dm_err_fp:
                    # Only report error if it wasn't already gone
                    err_msg = f"Failed to remove DM mapping {mapper_name} (and {lv_path}): {dm_err_fp}"
                    print(f"    Warning: {err_msg}")
                    errors.append(err_msg)
                    all_success = False # Mark as failure if any removal fails
                # else: Ignore "No such device" error on second attempt too
            # else: Ignore "No such device" error on first attempt

    if progress_callback:
        status = "DM removal complete." if all_success and not errors else "DM removal attempted, some errors occurred."
        progress_callback(f"DM Check on {disk_device}: {status}", None)

    final_error_str = "\n".join(errors)
    # Return success overall unless a removal failed with an error other than "No such device"
    return all_success, final_error_str 