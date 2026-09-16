"""Layers 2 and 3: kernel modules, /dev/video* presence, and device IDENTITY.

THE DEVICE NUMBER IS NOT AN IDENTITY. Detaching and re-attaching over usbipd
renumbers every node: on the rig the same two cameras came back as
video1..video8 having been video0..video7, so the webcam stopped being index 0
with nothing changing physically. Anything that remembers an index is wrong
after the next reboot, unplug or attach, and it fails by silently opening the
WRONG camera, which is far worse than failing to open one. Identify by USB
VID:PID from sysfs, and group nodes by physical device: a RealSense D435i
presents SIX /dev/video* nodes (depth, IR, colour, metadata) all with the
same name, of which exactly one delivers colour.
"""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field

REQUIRED_MODULES = ("vhci_hcd", "uvcvideo")


@dataclass
class VideoNode:
    index: int
    name: str = ""
    vidpid: str = ""
    usb_path: str = ""      # sysfs path of the USB device; same for sibling nodes

    @property
    def dev(self) -> str:
        return "/dev/video%d" % self.index


def video_nodes(dev_glob: str = "/dev/video*") -> list[int]:
    out = []
    for p in glob.glob(dev_glob):
        m = re.search(r"(\d+)$", p)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def identity(index: int, sysfs_root: str = "/sys/class/video4linux") -> VideoNode:
    """Card name and USB VID:PID for /dev/videoN, read from sysfs."""
    base = os.path.join(sysfs_root, "video%d" % index)
    node = VideoNode(index)
    try:
        with open(os.path.join(base, "name")) as fh:
            node.name = fh.read().strip()
    except OSError:
        return node
    d = os.path.realpath(base)
    for _ in range(8):          # walk up to the USB device node
        d = os.path.dirname(d)
        if not d or d == "/":
            break
        try:
            with open(os.path.join(d, "idVendor")) as fh:
                vid = fh.read().strip()
            with open(os.path.join(d, "idProduct")) as fh:
                pid = fh.read().strip()
        except OSError:
            continue
        node.vidpid = "%s:%s" % (vid.lower(), pid.lower())
        node.usb_path = d
        break
    return node


def all_identities(dev_glob: str = "/dev/video*",
                   sysfs_root: str = "/sys/class/video4linux") -> list[VideoNode]:
    return [identity(i, sysfs_root) for i in video_nodes(dev_glob)]


@dataclass
class Device:
    vidpid: str
    name: str
    nodes: list[VideoNode] = field(default_factory=list)


def group_by_device(nodes: list[VideoNode]) -> list[Device]:
    """Collapse sibling nodes into physical devices (RealSense: 6 nodes -> 1)."""
    groups: dict[str, Device] = {}
    for n in nodes:
        key = n.usb_path or n.vidpid or ("node%d" % n.index)
        if key not in groups:
            groups[key] = Device(n.vidpid or "?", n.name or "?")
        groups[key].nodes.append(n)
    return list(groups.values())


def loaded_modules(proc_modules: str = "/proc/modules") -> set[str]:
    try:
        with open(proc_modules) as fh:
            text = fh.read()
    except OSError:
        return set()
    return parse_modules(text)


def parse_modules(text: str) -> set[str]:
    return {line.split()[0].replace("-", "_") for line in text.splitlines() if line.strip()}


def missing_modules(loaded: set[str], required=REQUIRED_MODULES) -> list[str]:
    """Modules needed for usbip video that are not loaded.

    A module built INTO the kernel does not appear in /proc/modules, so this
    is only conclusive when combined with 'no /dev/video* exists'.
    """
    return [m for m in required if m.replace("-", "_") not in loaded]


def modprobe_fix(missing: list[str]) -> str:
    return "sudo modprobe %s" % " ".join(m.replace("_", "-") if m == "vhci_hcd" else m
                                         for m in missing)
