# centrio_installer/backend.py

import subprocess
import shlex
import os
import re # For parsing os-release
from .utils import get_os_release_info

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

def _run_in_container(target_root, command_list, description, progress_callback=None, timeout=None, pipe_input=None):
    """Runs a command inside the target root using systemd-nspawn (via _run_command)."""
    nspawn_cmd = [
        "systemd-nspawn", 
        "-q", 
        f"-D{target_root}",
        "--capability=all", 
        "--bind-ro=/etc/resolv.conf" 
    ] + command_list
    # _run_command will handle pkexec prepending if needed
    return _run_command(nspawn_cmd, description, progress_callback, timeout, pipe_input)

# --- Configuration Functions ---

def configure_system_in_container(target_root, config_data, progress_callback=None):
    """Configures timezone, locale, keyboard, hostname in target via systemd-nspawn."""
    
    # Timezone
    tz = config_data.get('timedate', {}).get('timezone')
    if tz:
        success, err, _ = _run_in_container(target_root, ["timedatectl", "set-timezone", tz], "Set Timezone", progress_callback, timeout=15)
        if not success: return False, err
    else:
        print("Skipping timezone configuration (not provided).")

    # Locale
    locale = config_data.get('language', {}).get('locale')
    if locale:
        success, err, _ = _run_in_container(target_root, ["localectl", "set-locale", f"LANG={locale}"], "Set Locale", progress_callback, timeout=15)
        if not success: return False, err
    else:
         print("Skipping locale configuration (not provided).")

    # Keymap
    keymap = config_data.get('keyboard', {}).get('layout')
    if keymap:
        success, err, _ = _run_in_container(target_root, ["localectl", "set-keymap", keymap], "Set Keymap", progress_callback, timeout=15)
        if not success: return False, err
    else:
        print("Skipping keymap configuration (not provided).")
        
    # Hostname
    hostname = config_data.get('network', {}).get('hostname')
    if hostname:
        success, err, _ = _run_in_container(target_root, ["hostnamectl", "set-hostname", hostname], "Set Hostname", progress_callback, timeout=15)
        if not success: return False, err
    else:
        print("Skipping hostname configuration (not provided).")

    return True, ""

def create_user_in_container(target_root, user_config, progress_callback=None):
    """Creates user account in target via systemd-nspawn."""
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
    
    success, err, _ = _run_in_container(target_root, useradd_cmd, f"Create User {username}", progress_callback, timeout=30)
    if not success: return False, err, None
    
    # Set password using chpasswd - only if password was provided
    if password is not None: # Check if password exists (even if empty string, let chpasswd decide)
        chpasswd_input = f"{username}:{password}"
        success, err, _ = _run_in_container(target_root, ["chpasswd"], f"Set Password for {username}", progress_callback, timeout=15, pipe_input=chpasswd_input)
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
        install_progress_re = re.compile(r"^(Installing|Updating|Upgrading|Cleanup|Verifying)\s*:.*?\s+(\d+)/(\d+)\s*$\"")
        # Simple count for total packages usually mentioned early
        total_packages_re = re.compile(r"Total download size:.*Installed size:.* Package count: (\\d+)\") # May not always appear

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
            return False, error_msg
        else:
             print(f"SUCCESS: DNF installation completed.")
             if progress_callback: progress_callback("DNF installation complete.", 1.0)
             # Optionally enable NetworkManager here (but requires _run_in_container, which uses _run_command)
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
# We need a function that uses _run_in_container (and thus _run_command for root check)
def enable_network_manager(target_root, progress_callback=None):
    """Enables NetworkManager service in the target system."""
    if progress_callback:
        progress_callback("Enabling NetworkManager service...", 0.96) # Example fraction
    
    nm_enable_cmd = ["systemctl", "enable", "NetworkManager.service"]
    success, err, _ = _run_in_container(target_root, nm_enable_cmd, "Enable NetworkManager Service", progress_callback=None, timeout=30)
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
    """Installs GRUB2 bootloader via systemd-nspawn."""
    
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

    success, err, _ = _run_in_container(target_root, grub_install_cmd, "Install GRUB", progress_callback, timeout=120)
    if not success: return False, err, None
    
    # Generate GRUB config
    # Ensure /boot is mounted correctly within the container context
    grub_mkconfig_cmd = ["grub2-mkconfig", "-o", "/boot/grub2/grub.cfg"]
    success, err, _ = _run_in_container(target_root, grub_mkconfig_cmd, "Generate GRUB Config", progress_callback, timeout=120)
    if not success: return False, err, None

    return True, "", None 