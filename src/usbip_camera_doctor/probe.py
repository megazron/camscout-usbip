"""Layer 4: a device that OPENS versus a device that DELIVERS.

A probe is a READ, not an open. The RealSense's depth and metadata nodes open
cleanly, accept every property, and return nothing for ever; a webcam over
usbip in its default YUYV format opens fine and then `select()` times out,
which is indistinguishable from a camera that sees nothing. So this walks a
ladder of (fourcc, width, height) and calls a node good only when a frame
actually arrives.

The default ladder starts at MJPG 640x480 on purpose:

* MJPG is mandatory over usbip for many webcams (measured on the rig: MJPG
  640x480 -> 24.9 fps; YUYV -> no frame, ever).
* 640x480 before 1280x720: a RealSense delivered at 640x480 over usbip and
  failed at 1280x720, and a 1280x720 raw ROS Image exceeds the default
  FastDDS shared-memory segment, so the node captures happily, reports live,
  and no subscriber ever receives a frame. 640x480 flows at ~32 Hz.

OpenCV is only imported here, and only when a probe is actually run.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import v4l2

DEFAULT_LADDER: list[tuple[str, int, int]] = [
    ("MJPG", 640, 480), ("MJPG", 1280, 720), ("YUYV", 640, 480)]

INSTALL_HINT = 'pip install "camscout-usbip[probe]"  (or: pip install opencv-python)'


def parse_ladder(text: str) -> list[tuple[str, int, int]]:
    """'MJPG:640x480,YUYV:1280x720' -> [("MJPG",640,480), ("YUYV",1280,720)]"""
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        fourcc, _, res = part.partition(":")
        w, _, h = res.lower().partition("x")
        if len(fourcc) != 4 or not w.isdigit() or not h.isdigit():
            raise ValueError("bad ladder rung %r; want FOURCC:WxH" % part)
        out.append((fourcc.upper(), int(w), int(h)))
    if not out:
        raise ValueError("empty ladder")
    return out


@dataclass
class Rung:
    fourcc: str
    width: int
    height: int
    opened: bool = False
    delivered: bool = False
    frames: int = 0
    seconds: float = 0.0
    actual: tuple[int, int] | None = None
    note: str = ""

    @property
    def fps(self) -> float:
        return self.frames / self.seconds if self.seconds > 0 and self.frames > 1 else 0.0


@dataclass
class ProbeResult:
    index: int
    identity: v4l2.VideoNode | None = None
    rungs: list[Rung] = field(default_factory=list)
    error: str = ""

    @property
    def delivers(self) -> bool:
        return any(r.delivered for r in self.rungs)

    @property
    def best(self) -> Rung | None:
        for r in self.rungs:
            if r.delivered:
                return r
        return None

    def why(self) -> str:
        if self.error:
            return self.error
        if self.delivers:
            b = self.best
            return "delivers %s %dx%d (~%.1f fps)" % (b.fourcc, b.width, b.height, b.fps)
        if self.rungs and not any(r.opened for r in self.rungs):
            return "will not open"
        tried = ", ".join("%s %dx%d" % (r.fourcc, r.width, r.height) for r in self.rungs)
        return "opens, delivers no frame in %.1f s (tried %s)" % (
            max((r.seconds for r in self.rungs), default=0.0), tried)


def _cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except Exception:  # noqa: BLE001
        return None


def deliver(index: int, ladder=None, timeout_s: float = 3.0,
            min_frames: int = 3, sysfs_root: str = "/sys/class/video4linux") -> ProbeResult:
    """Try each rung of the ladder on /dev/video<index>; stop at the first that delivers."""
    res = ProbeResult(index, v4l2.identity(index, sysfs_root))
    cv2 = _cv2()
    if cv2 is None:
        res.error = "opencv not importable; " + INSTALL_HINT
        return res
    for fourcc, w, h in (ladder or DEFAULT_LADDER):
        rung = Rung(fourcc, w, h)
        res.rungs.append(rung)
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        try:
            if not cap.isOpened():
                rung.note = "will not open"
                continue
            rung.opened = True
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            t0 = time.monotonic()
            t_first = None
            while time.monotonic() - t0 < timeout_s:
                ok, frame = cap.read()
                if ok and frame is not None:
                    if t_first is None:
                        t_first = time.monotonic()
                    rung.frames += 1
                    rung.actual = (int(frame.shape[1]), int(frame.shape[0]))
                    if rung.frames >= min_frames and time.monotonic() - t_first >= 0.5:
                        break
            rung.seconds = (time.monotonic() - t_first) if t_first else timeout_s
            rung.delivered = rung.frames > 0
            if rung.delivered:
                if rung.actual and rung.actual != (w, h):
                    rung.note = "driver substituted %dx%d" % rung.actual
                return res
            rung.note = "opens, delivers no frame in %.1f s" % timeout_s
        finally:
            cap.release()
    return res


def candidates(prefer_vidpid: str | None = None, exclude_vidpid=(),
               dev_glob: str = "/dev/video*",
               sysfs_root: str = "/sys/class/video4linux") -> list[v4l2.VideoNode]:
    """Video nodes ordered by how sure we are of the identification.

    1. VID:PID matches the preferred device
    2. anything with a card name that is not excluded
    3. whatever is left that is not excluded
    Excluded devices never appear: a RealSense colour node delivers frames
    perfectly, so a probe that only asks "does it deliver?" will happily pick
    it as the room camera and show a close-up of whatever the depth camera is
    pointed at.
    """
    ex = {v.lower() for v in exclude_vidpid}
    pref = prefer_vidpid.lower() if prefer_vidpid else None
    t1, t2, t3 = [], [], []
    for n in v4l2.all_identities(dev_glob, sysfs_root):
        if n.vidpid in ex:
            continue
        if pref and n.vidpid == pref:
            t1.append(n)
        elif n.name:
            t2.append(n)
        else:
            t3.append(n)
    return t1 + t2 + t3


def select_camera(prefer_vidpid: str | None = None, exclude_vidpid=(), ladder=None,
                  timeout_s: float = 3.0, dev_glob: str = "/dev/video*",
                  sysfs_root: str = "/sys/class/video4linux"):
    """(index or None, [ProbeResult...]) -- the first candidate that DELIVERS."""
    tried: list[ProbeResult] = []
    for n in candidates(prefer_vidpid, exclude_vidpid, dev_glob, sysfs_root):
        r = deliver(n.index, ladder, timeout_s, sysfs_root=sysfs_root)
        tried.append(r)
        if r.error:
            return None, tried
        if r.delivers:
            return n.index, tried
    return None, tried
