"""camera-doctor command line."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import doctor, openers, probe, ratemeter, rtsp, usbipd, v4l2


def _cmd_doctor(a) -> int:
    res = doctor.run(prefer=a.vidpid, exclude=a.exclude or (), rtsp_ips=a.rtsp or (),
                     rtsp_path=a.rtsp_path, watch_s=a.watch, stale_after_s=a.stale,
                     ladder=probe.parse_ladder(a.ladder) if a.ladder else None, timeout_s=a.timeout)
    print(doctor.render(res, a.json))
    return doctor.exit_code(res)


def _cmd_list(a) -> int:
    rows = []
    if doctor.is_wsl() or a.force_usbipd:
        devs, note = usbipd.list_devices()
        if devs:
            print("Windows (usbipd):")
            for d in devs:
                print("  %-8s %-9s %-11s %s" % (d.busid, d.vidpid, d.state, d.description))
        else:
            print("Windows (usbipd): %s" % note)
    ids = v4l2.all_identities()
    print("Linux (/dev/video*):")
    if not ids:
        missing = v4l2.missing_modules(v4l2.loaded_modules())
        print("  none" + ("  (modules not loaded: %s -> %s)" % (", ".join(missing), v4l2.modprobe_fix(missing))
                         if missing else ""))
    for d in v4l2.group_by_device(ids):
        print("  %-9s %-28s %s" % (d.vidpid, d.name, ", ".join(n.dev for n in d.nodes)))
        rows.append(asdict(d))
    if a.json:
        print(json.dumps(rows, indent=2))
    return 0


def _cmd_attach(a) -> int:
    devs, note = usbipd.list_devices()
    if not devs:
        print(note)
        return 1
    hits = usbipd.find(devs, a.vidpid, a.name)
    if not hits:
        print("no usbipd device matches vidpid=%r name=%r. Connected:" % (a.vidpid, a.name))
        for d in devs:
            print("  %-8s %-9s %-11s %s" % (d.busid, d.vidpid, d.state, d.description))
        return 1
    d = hits[0]
    print("%s  %s  %s  [%s]" % (d.busid, d.vidpid, d.description, d.state))
    steps = usbipd.attach_commands(d.busid, d.state)
    if not steps:
        print("already Attached; Linux nodes: %s" % (", ".join("/dev/video%d" % i for i in v4l2.video_nodes()) or "none (check kernel modules)"))
        return 0
    for cmd, where in steps:
        print("  %-45s # %s" % (cmd, where))
    if a.run:
        if d.state == "Not shared":
            print("cannot run: bind needs an Administrator PowerShell; run the bind line there first")
            return 1
        ok, msg = usbipd.attach(d.busid, a.wait)
        print(msg)
        return 0 if ok else 1
    return 0


def _cmd_probe(a) -> int:
    ladder = probe.parse_ladder(a.ladder) if a.ladder else None
    if a.index is not None:
        r = probe.deliver(a.index, ladder, a.timeout)
        results = [r]
        index = a.index if r.delivers else None
    else:
        index, results = probe.select_camera(a.vidpid, a.exclude or (), ladder, a.timeout)
    for r in results:
        ident = r.identity
        print("/dev/video%d  %s %s: %s" % (r.index, ident.vidpid or "?", ident.name or "?", r.why()))
        for rung in r.rungs:
            print("    %s %dx%d  opened=%s delivered=%s frames=%d %s" % (
                rung.fourcc, rung.width, rung.height, rung.opened, rung.delivered, rung.frames, rung.note))
    if index is None:
        print("no device delivered a frame")
        return 1
    print("selected /dev/video%d" % index)
    return 0


def _cmd_who(a) -> int:
    hs = openers.who(a.device)
    if not hs:
        print("%s: no process holds it" % a.device)
        return 0
    for h in hs:
        print("%s: pid %d %s  %s" % (a.device, h.pid, h.comm, h.cmdline[:100]))
    return 0


def _cmd_watch(a) -> int:
    m, note = ratemeter.watch(a.index, a.seconds, a.stale, a.fourcc, a.width, a.height)
    if m is None:
        print(note)
        return 1
    print(json.dumps(m.summary(), indent=2))
    return 0 if m.count else 1


def _cmd_rtsp(a) -> int:
    r = rtsp.probe(a.ip, a.path, a.port, a.timeout)
    print("%s %s: %s" % ("OK " if r.ok else "BAD", r.status, r.detail))
    return 0 if r.ok else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="camera-doctor",
                                 description="Name the first broken layer between a camera and your robot stack.")
    ap.add_argument("--vidpid", help="preferred camera as VID:PID, e.g. 32e4:0317")
    ap.add_argument("--exclude", action="append", help="VID:PID never to select (repeatable)")
    ap.add_argument("--rtsp", action="append", help="RTSP camera IP to probe (repeatable)")
    ap.add_argument("--rtsp-path", default="/color")
    ap.add_argument("--watch", type=float, default=0.0, help="seconds to meter the stream rate")
    ap.add_argument("--stale", type=float, default=0.5, help="stale threshold in seconds")
    ap.add_argument("--ladder", help="format ladder, e.g. MJPG:640x480,MJPG:1280x720,YUYV:640x480")
    ap.add_argument("--timeout", type=float, default=3.0, help="seconds to wait for a frame per rung")
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=_cmd_doctor)
    sub = ap.add_subparsers()

    p = sub.add_parser("list", help="usbipd devices and Linux video devices with identities")
    p.add_argument("--json", action="store_true")
    p.add_argument("--force-usbipd", action="store_true", help="query usbipd even outside WSL")
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("attach", help="print (or run) the usbipd commands for a camera")
    p.add_argument("--vidpid")
    p.add_argument("--name", help="regex on the usbipd description, e.g. 'HD USB CAMERA'")
    p.add_argument("--run", action="store_true", help="run the attach step and wait for /dev/video*")
    p.add_argument("--wait", type=float, default=10.0)
    p.set_defaults(func=_cmd_attach)

    p = sub.add_parser("probe", help="which node actually DELIVERS frames")
    p.add_argument("--index", type=int)
    p.add_argument("--vidpid")
    p.add_argument("--exclude", action="append")
    p.add_argument("--ladder")
    p.add_argument("--timeout", type=float, default=3.0)
    p.set_defaults(func=_cmd_probe)

    p = sub.add_parser("who", help="which process holds a device")
    p.add_argument("device")
    p.set_defaults(func=_cmd_who)

    p = sub.add_parser("watch", help="achieved rate and gaps")
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--stale", type=float, default=0.5)
    p.add_argument("--fourcc", default="MJPG")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.set_defaults(func=_cmd_watch)

    p = sub.add_parser("rtsp", help="does an RTSP camera serve (OPTIONS + DESCRIBE)")
    p.add_argument("ip")
    p.add_argument("--path", default="/color")
    p.add_argument("--port", type=int, default=554)
    p.add_argument("--timeout", type=float, default=6.0)
    p.set_defaults(func=_cmd_rtsp)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
