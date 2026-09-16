"""Layer 6: the stream's ACHIEVED rate and its gaps.

Always read the achieved rate; never assume the configured one. A RealSense
over usbip measured ~5 Hz at 640x480 with gaps up to 0.93 s. A panel with a
0.5 s STALE threshold flickered on every gap while the camera node itself
reported no dropout, because both were telling the truth about different
things. Raise the stale threshold to ~1.2-1.5 s for that link, and read the
gap statistics before calling a camera broken.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class RateMeter:
    stale_after_s: float = 0.5
    _t: list[float] = field(default_factory=list)

    def feed(self, t: float) -> None:
        self._t.append(float(t))

    @property
    def count(self) -> int:
        return len(self._t)

    @property
    def span_s(self) -> float:
        return (self._t[-1] - self._t[0]) if len(self._t) > 1 else 0.0

    @property
    def hz(self) -> float:
        return (len(self._t) - 1) / self.span_s if self.span_s > 0 else 0.0

    @property
    def gaps(self) -> list[float]:
        return [b - a for a, b in zip(self._t, self._t[1:])]

    @property
    def max_gap_s(self) -> float:
        g = self.gaps
        return max(g) if g else 0.0

    @property
    def stale_gaps(self) -> int:
        return sum(1 for g in self.gaps if g > self.stale_after_s)

    def is_stale(self, now: float) -> bool:
        return not self._t or (now - self._t[-1]) > self.stale_after_s

    def summary(self) -> dict:
        return {"frames": self.count, "span_s": round(self.span_s, 3),
                "hz": round(self.hz, 2), "max_gap_s": round(self.max_gap_s, 3),
                "gaps_over_stale": self.stale_gaps, "stale_after_s": self.stale_after_s}


def watch(index: int, seconds: float = 10.0, stale_after_s: float = 0.5,
          fourcc: str = "MJPG", width: int = 640, height: int = 480) -> tuple[RateMeter | None, str]:
    """Read frames from /dev/video<index> for `seconds` and meter them."""
    try:
        import cv2  # type: ignore
    except Exception:  # noqa: BLE001
        from .probe import INSTALL_HINT
        return None, "opencv not importable; " + INSTALL_HINT
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None, "/dev/video%d will not open" % index
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    m = RateMeter(stale_after_s)
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < seconds:
            ok, frame = cap.read()
            if ok and frame is not None:
                m.feed(time.monotonic())
    finally:
        cap.release()
    if m.count == 0:
        return m, "opened but delivered no frame in %.0f s" % seconds
    return m, "ok"
