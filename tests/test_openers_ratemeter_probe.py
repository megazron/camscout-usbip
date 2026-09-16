import os

import pytest

from usbip_camera_doctor import openers, probe
from usbip_camera_doctor.ratemeter import RateMeter


def fake_proc(tmp_path, procs):
    """procs: {pid: (comm, cmdline, [fd targets])}"""
    for pid, (comm, cmdline, fds) in procs.items():
        p = tmp_path / str(pid)
        (p / "fd").mkdir(parents=True)
        (p / "comm").write_text(comm + "\n")
        (p / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode() + b"\0")
        for i, t in enumerate(fds):
            os.symlink(t, p / "fd" / str(i))
    (tmp_path / "self").mkdir()      # non-numeric entries must be ignored
    return str(tmp_path)


def test_holders_from_proc(tmp_path):
    root = fake_proc(tmp_path, {
        1234: ("python3", "python3 quest_bridge_node.py", ["/dev/null", "/dev/video0"]),
        2345: ("bash", "bash", ["/dev/pts/0"]),
        3456: ("python3", "python3 scene_camera_node", ["/dev/video0"]),
    })
    hs, complete = openers.holders("/dev/video0", root)
    assert complete
    assert sorted(h.pid for h in hs) == [1234, 3456]
    assert hs[0].comm == "python3" and "quest_bridge_node" in hs[0].cmdline or "scene_camera" in hs[0].cmdline


def test_no_holder(tmp_path):
    root = fake_proc(tmp_path, {99: ("x", "x", ["/dev/video1"])})
    assert openers.who("/dev/video0", root) == []


def test_ratemeter_hz_and_gaps():
    m = RateMeter(stale_after_s=0.5)
    t = 0.0
    for _ in range(20):          # 20 Hz for 1 s
        m.feed(t); t += 0.05
    m.feed(t + 0.93)             # one 0.98 s gap
    assert m.count == 21
    assert m.stale_gaps == 1
    assert m.max_gap_s == pytest.approx(0.98, abs=1e-6)
    assert 9.5 < m.hz < 10.5     # 20 intervals over ~1.93 s
    assert m.is_stale(m._t[-1] + 0.6) and not m.is_stale(m._t[-1] + 0.1)
    s = m.summary()
    assert s["gaps_over_stale"] == 1 and s["frames"] == 21


def test_ratemeter_empty():
    m = RateMeter()
    assert m.hz == 0.0 and m.max_gap_s == 0.0 and m.is_stale(10.0)


def test_parse_ladder():
    assert probe.parse_ladder("MJPG:640x480, yuyv:1280X720") == [("MJPG", 640, 480), ("YUYV", 1280, 720)]
    with pytest.raises(ValueError):
        probe.parse_ladder("MJPEG:640x480")
    with pytest.raises(ValueError):
        probe.parse_ladder("")


def test_probe_result_why():
    r = probe.ProbeResult(3)
    r.rungs.append(probe.Rung("MJPG", 640, 480, opened=False, note="will not open"))
    assert r.why() == "will not open"
    r2 = probe.ProbeResult(4)
    r2.rungs.append(probe.Rung("MJPG", 640, 480, opened=True, seconds=3.0))
    assert "opens, delivers no frame" in r2.why()
    r3 = probe.ProbeResult(6)
    r3.rungs.append(probe.Rung("MJPG", 640, 480, opened=True, delivered=True, frames=10, seconds=0.5))
    assert r3.delivers and "delivers MJPG 640x480" in r3.why()


def test_deliver_without_opencv_reports_hint(monkeypatch):
    monkeypatch.setattr(probe, "_cv2", lambda: None)
    r = probe.deliver(0)
    assert not r.delivers and "opencv" in r.error and "pip install" in r.error
