"""Layer 1: the Windows -> WSL2 hand-over with usbipd-win.

There is no USB inside WSL2. A camera (or a Teensy, or anything on USB) has
to be handed over from Windows with `usbipd`, and when it has not been the
failure is silent in the worst way: /dev/video* simply does not exist, which
looks identical to an empty room.

Rules learned the hard way:

* `usbipd bind --busid X` needs an ADMINISTRATOR PowerShell. Once per device,
  survives reboots. `usbipd attach --wsl --busid X` needs no admin and is
  needed after EVERY reboot and every unplug.
* BUSIDS MOVE BETWEEN SESSIONS. On the rig, 3-2 was the RealSense one day and
  a Logitech receiver two days later; the RealSense had moved to 3-3. Look a
  device up by VID:PID (or its description), never by a remembered busid.
* The usbipd Windows service stops on its own on some machines
  (`Start-Service usbipd` in an admin PowerShell brings it back). When it is
  down, the cameras AND the serial devices vanish together, which reads as
  three unrelated faults.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

DEFAULT_EXE = "/mnt/c/Program Files/usbipd-win/usbipd.exe"

_ROW = re.compile(
    r"^(?P<busid>\d+-\d+(?:\.\d+)*)\s+"
    r"(?P<vidpid>[0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+"
    r"(?P<desc>.*?)\s+"
    r"(?P<state>Not shared|Shared(?: \(forced\))?|Attached|Persisted)\s*$")


@dataclass(frozen=True)
class UsbDevice:
    busid: str
    vidpid: str
    description: str
    state: str          # "Not shared" | "Shared" | "Attached" | "Persisted"

    @property
    def shared(self) -> bool:
        return self.state.startswith("Shared") or self.state == "Attached"

    @property
    def attached(self) -> bool:
        return self.state == "Attached"


def parse_usbipd_list(text: str) -> list[UsbDevice]:
    """Parse the output of `usbipd list` into devices. Pure; safe to unit test.

    Only the "Connected:" section is parsed; the "Persisted:" section lists
    devices that are not currently plugged in.
    """
    out: list[UsbDevice] = []
    in_persisted = False
    for raw in text.replace("\r", "").splitlines():
        line = raw.rstrip()
        if line.lower().startswith("persisted:"):
            in_persisted = True
            continue
        if line.lower().startswith("connected:"):
            in_persisted = False
            continue
        if in_persisted:
            continue
        m = _ROW.match(line)
        if m:
            out.append(UsbDevice(m.group("busid"), m.group("vidpid").lower(),
                                 m.group("desc").strip(), m.group("state")))
    return out


def usbipd_command() -> list[str] | None:
    """How to invoke usbipd from here, or None if there is no route."""
    exe = shutil.which("usbipd.exe") or shutil.which("usbipd")
    if exe:
        return [exe]
    if os.path.exists(DEFAULT_EXE):
        return [DEFAULT_EXE]
    ps = shutil.which("powershell.exe")
    if ps:
        return [ps, "-NoProfile", "-Command", "usbipd"]
    return None


def run_list(timeout: float = 20.0) -> tuple[str | None, str]:
    """(raw text, note). text is None when usbipd cannot be reached."""
    cmd = usbipd_command()
    if cmd is None:
        return None, ("usbipd is not reachable from this shell: no usbipd.exe on "
                      "PATH, nothing at %s, and no powershell.exe interop. Install "
                      "it once from an admin PowerShell: winget install usbipd"
                      % DEFAULT_EXE)
    try:
        p = subprocess.run(cmd + ["list"], capture_output=True, text=True,
                           timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return None, "usbipd list failed to run: %r" % (e,)
    text = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0 and "service" in text.lower():
        return None, ("usbipd answered but its Windows service is not running. "
                      "In an ADMINISTRATOR PowerShell: Start-Service usbipd")
    if p.returncode != 0:
        return None, "usbipd list exited %d: %s" % (p.returncode, text.strip()[:200])
    return text, "ok"


def list_devices(timeout: float = 20.0) -> tuple[list[UsbDevice], str]:
    text, note = run_list(timeout)
    if text is None:
        return [], note
    return parse_usbipd_list(text), note


def find(devices: list[UsbDevice], vidpid: str | None = None,
         name_regex: str | None = None) -> list[UsbDevice]:
    """Devices matching a VID:PID and/or a case-insensitive description regex."""
    out = devices
    if vidpid:
        v = vidpid.lower()
        out = [d for d in out if d.vidpid == v]
    if name_regex:
        rx = re.compile(name_regex, re.IGNORECASE)
        out = [d for d in out if rx.search(d.description)]
    return out


def attach_commands(busid: str, state: str) -> list[tuple[str, str]]:
    """The exact commands to get `busid` into WSL, as (command, where-to-run).

    Nothing is returned for a device that is already Attached.
    """
    steps: list[tuple[str, str]] = []
    if state == "Attached":
        return steps
    if state == "Not shared":
        steps.append(("usbipd bind --busid %s" % busid,
                      "ADMINISTRATOR PowerShell, once per device; survives reboots"))
    steps.append(("usbipd attach --wsl --busid %s" % busid,
                  "any PowerShell or from WSL via usbipd.exe; after every reboot "
                  "and every unplug; no admin needed"))
    return steps


def attach(busid: str, wait_s: float = 10.0,
           video_glob: str = "/dev/video*") -> tuple[bool, str]:
    """Run the attach step and wait for a NEW /dev/video* node to appear."""
    cmd = usbipd_command()
    if cmd is None:
        return False, "usbipd not reachable"
    before = set(glob.glob(video_glob))
    try:
        p = subprocess.run(cmd + ["attach", "--wsl", "--busid", busid],
                           capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa: BLE001
        return False, "attach failed to run: %r" % (e,)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if p.returncode != 0 and "already attached" not in out.lower():
        if "access denied" in out.lower() or "administrator" in out.lower():
            return False, ("the device is not shared yet; `usbipd bind --busid %s` "
                           "needs an ADMINISTRATOR PowerShell first" % busid)
        return False, "attach exited %d: %s" % (p.returncode, out[:300])
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait_s:
        new = set(glob.glob(video_glob)) - before
        if new:
            return True, "attached; new nodes: %s" % ", ".join(sorted(new))
        time.sleep(0.5)
    return False, ("usbipd reports the device attached but no new %s appeared in "
                   "%.0f s. Check the kernel modules (camera-doctor list): "
                   "vhci-hcd and uvcvideo are not loaded by default."
                   % (video_glob, wait_s))
