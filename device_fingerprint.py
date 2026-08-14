"""
device_fingerprint.py
======================
Generates a unique fingerprint for the device.
Used to prevent trial abuse — one trial per device regardless of email.
The fingerprint is a one-way hash so no personal data is stored.
"""

import hashlib
import platform
import uuid
import os


def get_fingerprint():
    """
    Generates a stable unique fingerprint for this device.

    This must NEVER raise. The desktop app sends it on login, and the
    website uses its presence to start the free trial — so a crash here
    would leave a user unable to start their trial at all.
    """
    try:
        return _build_fingerprint()
    except Exception:
        # Last-resort fallback: still stable per machine, just coarser.
        try:
            raw = f"{platform.node()}|{platform.system()}|{uuid.getnode()}"
        except Exception:
            raw = "unknown-device"
        return hashlib.sha256(raw.encode()).hexdigest()


def _build_fingerprint():
    """
    Generates a stable unique fingerprint for this device.
    Uses a combination of hardware identifiers that don't change
    between reboots or reinstalls.
    
    Returns a 64-character hex string.
    """
    components = []

    # Machine hostname
    components.append(platform.node())

    # OS details
    components.append(platform.system())
    components.append(platform.version())
    components.append(platform.machine())

    # CPU info
    components.append(platform.processor())

    # MAC address (network card hardware ID)
    mac = uuid.UUID(int=uuid.getnode()).hex
    components.append(mac)

    # Windows machine GUID (most stable identifier on Windows)
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography"
            )
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            components.append(machine_guid)
        except Exception:
            pass

    # Mac hardware UUID
    elif platform.system() == "Darwin":
        try:
            import subprocess
            result = subprocess.check_output(
                ["system_profiler", "SPHardwareDataType"],
                stderr=subprocess.DEVNULL
            ).decode()
            for line in result.split("\n"):
                if "Hardware UUID" in line:
                    components.append(line.split(":")[1].strip())
                    break
        except Exception:
            pass

    # Combine and hash everything
    raw = "|".join(components)
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()
    return fingerprint
