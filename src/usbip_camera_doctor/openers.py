"""Layer 5: who holds the device.

A V4L2 device cannot be opened twice for capture. When two nodes want
/dev/video0, whichever starts first wins and the other silently gets nothing,
so the camera "works sometimes" depending on start order. On the rig
`fuser /dev/video0` named the VR bridge while the scene camera node reported
BUSY.

THE CORRECT YIELD RULE: the process that does not own the device yields when
the owning node's PUBLISHER EXISTS, never when its frames arrive. The first
fix yielded on frames and deadlocked:

    bridge holds /dev/video0 -> camera node cannot open it -> it never
    publishes -> "is it publishing?" is false -> bridge keeps the device

A publisher exists as soon as a node constructs, before it opens any device,
so asking the graph breaks the cycle.

This module needs no `fuser`: it reads /proc/<pid>/fd, and falls back to
`fuser -v` only when /proc is not readable for other users' processes.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Holder:
    pid: int
    comm: str
    cmdline: str


def _read(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def holders(device: str, proc_root: str = "/proc") -> tuple[list[Holder], bool]:
    """([Holder...], complete) -- complete is False if some /proc/<pid>/fd was unreadable."""
    device = os.path.realpath(device) if os.path.exists(device) else device
    out: list[Holder] = []
    complete = True
    for pid in os.listdir(proc_root):
        if not pid.isdigit():
            continue
        fd_dir = os.path.join(proc_root, pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except PermissionError:
            complete = False
            continue
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if target == device:
                out.append(Holder(int(pid), _read(os.path.join(proc_root, pid, "comm")),
                                  _read(os.path.join(proc_root, pid, "cmdline"))))
                break
    return out, complete


def holders_via_fuser(device: str) -> list[Holder]:
    if not shutil.which("fuser"):
        return []
    try:
        p = subprocess.run(["fuser", "-v", device], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for line in (p.stderr + p.stdout).splitlines():
        parts = line.split()
        for tok in parts:
            if tok.isdigit():
                pid = int(tok)
                out.append(Holder(pid, _read("/proc/%d/comm" % pid), _read("/proc/%d/cmdline" % pid)))
                break
    return out


def who(device: str, proc_root: str = "/proc") -> list[Holder]:
    hs, complete = holders(device, proc_root)
    if not hs and not complete:
        hs = holders_via_fuser(device)
    return hs
