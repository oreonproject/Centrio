# centrio_installer/backend.py

import subprocess
import shlex
import os
import re # For parsing os-release
from .utils import get_os_release_info

def _run_command(command_list, description, progress_callback=None, timeout=None, pipe_input=None):
    """Runs a command via pkexec, captures output, handles errors, and calls progress callback."""
    
    # Prepend pkexec to the command list
    pkexec_command_list = ["pkexec"] + command_list
    
    cmd_str = ' '.join(shlex.quote(c) for c in pkexec_command_list)
    print(f"Executing Backend Step (via pkexec): {description} -> {cmd_str}")
    if progress_callback:
        progress_callback(f"Requesting privileges for: {description}...")
        
    stderr_output = ""
    try:
        # Run the command with pkexec
        process = subprocess.Popen(
            pkexec_command_list, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if pipe_input is not None else None,
            text=True
        )
        
        stdout, stderr = process.communicate(input=pipe_input, timeout=timeout)
        stderr_output = stderr 
        
        print(f"  Command {description} stdout:\n{stdout.strip()}")
        if stderr:
             # Filter out common pkexec info messages if desired
             filtered_stderr = "\n".join(line for line in stderr.splitlines() if "using backend" not in line)
             if filtered_stderr.strip():
                 print(f"  Command {description} stderr:\n{filtered_stderr.strip()}")

        if process.returncode != 0:
            error_detail = stderr.strip() or f"Exited with code {process.returncode}"
            # Check for common pkexec/PolicyKit errors
            if "Authentication failed" in error_detail or process.returncode == 127:
                 error_msg = f"Authorization failed for {description}. Check PolicyKit rules or password."
            elif "Cannot run program" in error_detail or process.returncode == 126:
                 error_msg = f"Command not found or not permitted by PolicyKit for {description}: {command_list[0]}"
            else:
                error_msg = f"{description} failed: {error_detail}"
            print(f"ERROR: {error_msg}")
            return False, error_msg
            
        print(f"SUCCESS: {description} completed.")
        return True, ""

    except FileNotFoundError:
        # This likely means pkexec itself wasn't found
        err = "Command not found: pkexec. Cannot run privileged commands."
        print(f"ERROR: {err}")
        return False, err
    except subprocess.TimeoutExpired:
        err = f"Timeout expired after {timeout}s for {description} (via pkexec)."
        # Try to kill the process if it timed out during communicate
        try:
            process.kill()
            process.wait() # Wait for the process to terminate
        except Exception as kill_e:
            print(f"Warning: Error trying to kill timed out pkexec process: {kill_e}")
        return False, err
    except Exception as e:
        # Include stderr if available, otherwise just the exception
        err_detail = stderr_output.strip() or str(e)
        err = f"Unexpected error during {description} (via pkexec): {err_detail}"
        print(f"ERROR: {err}")
        return False, err

def _run_in_container(target_root, command_list, description, progress_callback=None, timeout=None, pipe_input=None):
    """Runs a command inside the target root using systemd-nspawn (via pkexec)."""
    # Requires systemd-nspawn to be installed and user running installer to have permissions
    # -q: quiet
    # -D: directory to use as root
    # --capability=all: Grant all capabilities (might need refinement for security)
    # --bind-ro=/etc/resolv.conf: Needed for network access within container
    nspawn_cmd = [
        "systemd-nspawn", 
        "-q", 
        f"-D{target_root}",
        "--capability=all", 
        "--bind-ro=/etc/resolv.conf" 
    ] + command_list
    # _run_command will prepend pkexec to nspawn_cmd
    return _run_command(nspawn_cmd, description, progress_callback, timeout, pipe_input)

# --- Configuration Functions ---

def configure_system_in_container(target_root, config_data, progress_callback=None):
    """Configures timezone, locale, keyboard, hostname in target via systemd-nspawn."""
    
    # Timezone
    tz = config_data.get('timedate', {}).get('timezone')
    if tz:
        success, err = _run_in_container(target_root, ["timedatectl", "set-timezone", tz], "Set Timezone", progress_callback, timeout=15)
        if not success: return False, err
    else:
        print("Skipping timezone configuration (not provided).")

    # Locale
    locale = config_data.get('language', {}).get('locale')
    if locale:
        success, err = _run_in_container(target_root, ["localectl", "set-locale", f"LANG={locale}"], "Set Locale", progress_callback, timeout=15)
        if not success: return False, err
    else:
         print("Skipping locale configuration (not provided).")

    # Keymap
    keymap = config_data.get('keyboard', {}).get('layout')
    if keymap:
        success, err = _run_in_container(target_root, ["localectl", "set-keymap", keymap], "Set Keymap", progress_callback, timeout=15)
        if not success: return False, err
    else:
        print("Skipping keymap configuration (not provided).")
        
    # Hostname
    hostname = config_data.get('network', {}).get('hostname')
    if hostname:
        success, err = _run_in_container(target_root, ["hostnamectl", "set-hostname", hostname], "Set Hostname", progress_callback, timeout=15)
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
        return False, "Username not provided in user configuration."
    # Allow proceeding even if password is None or empty, chpasswd might handle it or fail later
    # if not password:
    #      return False, "Password not provided for user creation."

    # Build useradd command
    useradd_cmd = ["useradd", "-m", "-s", "/bin/bash", "-U"]
    if real_name:
        useradd_cmd.extend(["-c", real_name])
    if is_admin:
        useradd_cmd.extend(["-G", "wheel"]) # Add to wheel group for sudo
    useradd_cmd.append(username)
    
    success, err = _run_in_container(target_root, useradd_cmd, f"Create User {username}", progress_callback, timeout=30)
    if not success: return False, err
    
    # Set password using chpasswd - only if password was provided
    if password is not None: # Check if password exists (even if empty string, let chpasswd decide)
        chpasswd_input = f"{username}:{password}"
        success, err = _run_in_container(target_root, ["chpasswd"], f"Set Password for {username}", progress_callback, timeout=15, pipe_input=chpasswd_input)
        if not success: 
            print(f"Warning: Failed to set password for {username} after user creation: {err}")
            # Decide if this should be a fatal error for the whole installation
            # return False, err # Stop installation if password set fails?
            pass # Continue for now
    else:
         print(f"Warning: No password provided for user {username}. Account created without password set.")
        
    return True, ""

# --- Package Installation ---

def install_packages_dnf(target_root, progress_callback=None):
    """Installs base packages using DNF --installroot."""
    
    os_info = get_os_release_info() 
    releasever = os_info.get("VERSION_ID")
    if not releasever:
        print("Warning: Could not detect OS VERSION_ID. Falling back to 40.")
        releasever = "40" 
    print(f"Using release version: {releasever}")
        
    # Refined package set for a basic graphical system (example)
    packages = [
        "@core", "kernel", "grub2-efi-x64", "grub2-pc", "efibootmgr", 
        "linux-firmware", "NetworkManager", "systemd-resolved", 
        # Add a minimal desktop environment if desired (e.g., XFCE)
        # "@xfce-desktop-environment", "lightdm"
        # Or just essentials
        "bash-completion", "dnf-utils"
    ]
    
    dnf_cmd = [
        "dnf", 
        "install", 
        "-y", 
        "--nogpgcheck", # Allow installation without GPG key checking (Use with caution!)
        f"--installroot={target_root}",
        f"--releasever={releasever}",
        f"--setopt=install_weak_deps=False"
    ] + packages

    success, err = _run_command(dnf_cmd, "Install Base Packages (DNF)", progress_callback, timeout=3600) # Increase timeout to 1 hour
    if not success: return False, err
    
    # Optionally, enable NetworkManager service in the installed system
    nm_enable_cmd = ["systemctl", "enable", "NetworkManager.service"]
    success, err = _run_in_container(target_root, nm_enable_cmd, "Enable NetworkManager Service", progress_callback, timeout=30)
    if not success: 
        print(f"Warning: Failed to enable NetworkManager service: {err}")
        # Continue installation even if service enabling fails?
        pass 

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

    success, err = _run_in_container(target_root, grub_install_cmd, "Install GRUB", progress_callback, timeout=120)
    if not success: return False, err
    
    # Generate GRUB config
    # Ensure /boot is mounted correctly within the container context
    grub_mkconfig_cmd = ["grub2-mkconfig", "-o", "/boot/grub2/grub.cfg"]
    success, err = _run_in_container(target_root, grub_mkconfig_cmd, "Generate GRUB Config", progress_callback, timeout=120)
    if not success: return False, err

    return True, "" 