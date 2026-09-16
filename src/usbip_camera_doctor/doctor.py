"""Walk the layers in order and stop at the first one that is broken.

A fault at layer 2 makes every answer above it meaningless, so the doctor
does not report seven independent verdicts; it reports the FIRST wrong layer
in the operator's words, with the fix, and the layers above it as SKIP.
"""
from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field

from . import openers, probe as probe_mod, rtsp as rtsp_mod, usbipd, v4l2
from .ratemeter import watch as watch_mod

OK, BROKEN, SKIP, UNKNOWN = "ok", "BROKEN", "SKIP", "CANNOT TELL"


@dataclass
class LayerResult:
    name: str
    status: str
    detail: str
    fix: str = ""
    data: dict = field(default_factory=dict)


def is_wsl() -> bool:
    try:
        with open("/proc/version") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def run(prefer: str | None = None, exclude=(), rtsp_ips=(), rtsp_path: str = "/color",
        watch_s: float = 0.0, stale_after_s: float = 0.5, ladder=None, timeout_s: float = 3.0,
        *, dev_glob: str = "/dev/video*", sysfs_root: str = "/sys/class/video4linux",
        proc_root: str = "/proc", proc_modules: str = "/proc/modules",
        usbipd_text=None, wsl=None, prober=None) -> list[LayerResult]:
    """Run the layers. Keyword-only parameters exist so tests can inject fakes."""
    out: list[LayerResult] = []
    wsl = is_wsl() if wsl is None else wsl
    nodes = v4l2.video_nodes(dev_glob)

    # ---- layer 1: usbipd hand-over (WSL only)
    if wsl:
        if usbipd_text is None:
            text, note = usbipd.run_list()
        else:
            text, note = usbipd_text, "ok"
        if text is None:
            if nodes:
                out.append(LayerResult("usbipd hand-over", UNKNOWN,
                                       "%s -- but %d /dev/video* node(s) exist, so something "
                                       "was handed over" % (note, len(nodes))))
            else:
                out.append(LayerResult("usbipd hand-over", BROKEN, note,
                                       "install/start usbipd on Windows, then attach the camera"))
                return _skip_rest(out, ("kernel modules", "video devices", "identity",
                                        "frame delivery", "exclusive openers", "stream rate"))
        else:
            devs = usbipd.parse_usbipd_list(text)
            cams = [d for d in devs if "camera" in d.description.lower()
                    or "realsense" in d.description.lower() or "webcam" in d.description.lower()
                    or (prefer and d.vidpid == prefer.lower())]
            attached = [d for d in cams if d.attached]
            if cams and not attached and not nodes:
                d = cams[0]
                cmds = "; ".join(c for c, _ in usbipd.attach_commands(d.busid, d.state))
                out.append(LayerResult("usbipd hand-over", BROKEN,
                                       "Windows sees '%s' (%s, busid %s) but it is %s, not "
                                       "Attached" % (d.description, d.vidpid, d.busid, d.state),
                                       cmds, {"devices": [asdict(x) for x in cams]}))
                return _skip_rest(out, ("kernel modules", "video devices", "identity",
                                        "frame delivery", "exclusive openers", "stream rate"))
            if not cams and not nodes:
                out.append(LayerResult("usbipd hand-over", BROKEN,
                                       "no camera-like device is connected to Windows at all "
                                       "(%d USB devices listed)" % len(devs),
                                       "plug the camera in; camera-doctor list"))
                return _skip_rest(out, ("kernel modules", "video devices", "identity",
                                        "frame delivery", "exclusive openers", "stream rate"))
            out.append(LayerResult("usbipd hand-over", OK,
                                   "%d camera-like device(s), %d Attached" % (len(cams), len(attached)),
                                   data={"devices": [asdict(x) for x in cams]}))
    else:
        out.append(LayerResult("usbipd hand-over", SKIP, "not WSL; USB is native"))

    # ---- layer 2: kernel modules + /dev/video*
    missing = v4l2.missing_modules(v4l2.loaded_modules(proc_modules))
    if not nodes:
        if missing:
            out.append(LayerResult("kernel modules", BROKEN,
                                   "no /dev/video* and %s not loaded: usbipd can say Attached "
                                   "while Linux has no video device" % ", ".join(missing),
                                   v4l2.modprobe_fix(missing)))
        else:
            out.append(LayerResult("kernel modules", OK, "vhci-hcd and uvcvideo loaded"))
            out.append(LayerResult("video devices", BROKEN, "no /dev/video* exists",
                                   "camera-doctor attach --vidpid <vid:pid> --run"))
        return _skip_rest(out, ("identity", "frame delivery", "exclusive openers", "stream rate"))
    out.append(LayerResult("kernel modules", OK,
                           "loaded" if not missing else "not in /proc/modules (%s) but devices "
                           "exist, so they are built in" % ", ".join(missing)))
    out.append(LayerResult("video devices", OK, "%d node(s): %s" % (
        len(nodes), ", ".join("/dev/video%d" % n for n in nodes))))

    # ---- layer 3: identity
    ids = v4l2.all_identities(dev_glob, sysfs_root)
    devices = v4l2.group_by_device(ids)
    desc = "; ".join("%s %s -> %s" % (d.vidpid, d.name, ",".join("video%d" % n.index for n in d.nodes))
                     for d in devices)
    if prefer and not any(d.vidpid == prefer.lower() for d in devices):
        out.append(LayerResult("identity", BROKEN,
                               "no device with VID:PID %s among: %s" % (prefer, desc),
                               "camera-doctor attach --vidpid %s --run" % prefer,
                               {"devices": [asdict(d) for d in devices]}))
        return _skip_rest(out, ("frame delivery", "exclusive openers", "stream rate"))
    out.append(LayerResult("identity", OK, desc, data={"devices": [asdict(d) for d in devices]}))

    # ---- layer 4: frame delivery
    prober = prober or probe_mod.select_camera
    index, tried = prober(prefer, exclude, ladder, timeout_s, dev_glob, sysfs_root)
    if tried and tried[0].error:
        out.append(LayerResult("frame delivery", SKIP, tried[0].error, probe_mod.INSTALL_HINT))
        out.append(LayerResult("exclusive openers", SKIP, "needs the probe"))
        out.append(LayerResult("stream rate", SKIP, "needs the probe"))
        for ip in rtsp_ips:
            out.append(_rtsp_layer(ip, rtsp_path))
        return out
    elif index is None:
        why = "; ".join("video%d: %s" % (r.index, r.why()) for r in tried) or "no candidates"
        holders = {}
        for r in tried:
            hs = openers.who("/dev/video%d" % r.index, proc_root)
            if hs:
                holders["video%d" % r.index] = ["%d %s" % (h.pid, h.comm) for h in hs]
        fix = ("another process holds the device: %s" % holders) if holders else \
              "try MJPG at 640x480; re-attach the device; check the usbip link bandwidth"
        out.append(LayerResult("frame delivery", BROKEN, "no candidate delivered a frame: " + why,
                               fix, {"tried": [r.why() for r in tried], "holders": holders}))
        out.append(LayerResult("exclusive openers", BROKEN if holders else SKIP,
                               str(holders) if holders else "no other opener found"))
        return _skip_rest(out, ("stream rate",))
    best = tried[-1].best
    out.append(LayerResult("frame delivery", OK, "/dev/video%d %s" % (index, tried[-1].why()),
                           data={"index": index, "fourcc": best.fourcc, "width": best.width,
                                 "height": best.height, "fps": round(best.fps, 2)}))

    # ---- layer 5: exclusive openers (informational once we could read)
    hs = openers.who("/dev/video%d" % index, proc_root)
    others = [h for h in hs if h.pid != os.getpid()]
    out.append(LayerResult("exclusive openers", OK if not others else UNKNOWN,
                           "device is free" if not others else
                           "held by %s" % ", ".join("%d %s" % (h.pid, h.comm) for h in others),
                           "" if not others else "a second opener of a V4L2 device silently gets "
                                                  "nothing; make the holder yield when your publisher exists"))

    # ---- layer 6: stream rate
    if watch_s > 0:
        m, note = watch_mod(index, watch_s, stale_after_s, best.fourcc, best.width, best.height)
        if m is None or m.count == 0:
            out.append(LayerResult("stream rate", BROKEN, note))
        else:
            s = m.summary()
            status = OK if s["gaps_over_stale"] == 0 else UNKNOWN
            out.append(LayerResult("stream rate", status,
                                   "%.1f Hz, max gap %.2f s, %d gap(s) over %.1f s" % (
                                       s["hz"], s["max_gap_s"], s["gaps_over_stale"], stale_after_s),
                                   "" if status == OK else "raise the consumer's stale threshold above "
                                                          "the max gap before calling the camera broken", s))
    else:
        out.append(LayerResult("stream rate", SKIP, "pass --watch SECONDS to measure"))

    # ---- layer 7: RTSP
    for ip in rtsp_ips:
        out.append(_rtsp_layer(ip, rtsp_path))
    return out


def _rtsp_layer(ip: str, path: str) -> LayerResult:
    r = rtsp_mod.probe(ip, path)
    return LayerResult("rtsp %s" % ip, OK if r.ok else BROKEN, r.detail,
                       "" if r.ok else ("power-cycle the device" if r.status == "wedged"
                                        else "check the address and the stream path"),
                       {"status": r.status, "fps": r.fps})


def _skip_rest(out: list[LayerResult], names) -> list[LayerResult]:
    for n in names:
        out.append(LayerResult(n, SKIP, "not reached: a lower layer is broken"))
    return out


def render(results: list[LayerResult], as_json: bool = False) -> str:
    if as_json:
        return json.dumps([asdict(r) for r in results], indent=2)
    width = max(len(r.name) for r in results) if results else 10
    lines = ["== CAMERA DOCTOR == (%s%s)" % (platform.node(), ", WSL" if is_wsl() else "")]
    for r in results:
        lines.append("  %-*s  %-12s %s" % (width, r.name, r.status, r.detail))
        if r.fix and r.status in (BROKEN, UNKNOWN, SKIP) and r.fix != r.detail:
            lines.append("  %-*s  %-12s fix: %s" % (width, "", "", r.fix))
    broken = [r for r in results if r.status == BROKEN]
    lines.append("")
    lines.append("verdict: %s" % ("all reachable layers ok" if not broken else
                                  "first broken layer is '%s'" % broken[0].name))
    return "\n".join(lines)


def exit_code(results: list[LayerResult]) -> int:
    return 1 if any(r.status == BROKEN for r in results) else 0
