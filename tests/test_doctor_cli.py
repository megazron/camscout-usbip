import json
import os

from usbip_camera_doctor import cli, doctor, probe

USBIPD_NOT_ATTACHED = """Connected:
BUSID  VID:PID    DEVICE                       STATE
2-9    32e4:0317  HD USB CAMERA, HD USB CAMERA Shared
"""
USBIPD_ATTACHED = USBIPD_NOT_ATTACHED.replace("Shared\n", "Attached\n")


def _fake_sysfs(tmp_path, idx=0):
    root = tmp_path / "v4l"; root.mkdir()
    usb = tmp_path / "usb"; usb.mkdir()
    (usb / "idVendor").write_text("32e4"); (usb / "idProduct").write_text("0317")
    node = usb / "if" / "video4linux" / ("video%d" % idx); node.mkdir(parents=True)
    (node / "name").write_text("HD USB CAMERA")
    os.symlink(node, root / ("video%d" % idx))
    return str(root)


def _fake_dev(tmp_path, idx=0):
    d = tmp_path / "dev"; d.mkdir(exist_ok=True)
    (d / ("video%d" % idx)).write_text("")
    return str(d / "video*")


def _modules(tmp_path, text):
    p = tmp_path / "modules"; p.write_text(text); return str(p)


def test_stops_at_usbipd_when_not_attached_and_no_device(tmp_path):
    res = doctor.run(wsl=True, usbipd_text=USBIPD_NOT_ATTACHED, dev_glob=str(tmp_path / "none*"),
                     proc_modules=_modules(tmp_path, ""))
    assert res[0].name == "usbipd hand-over" and res[0].status == doctor.BROKEN
    assert "usbipd attach --wsl --busid 2-9" in res[0].fix
    assert all(r.status == doctor.SKIP for r in res[1:])
    assert doctor.exit_code(res) == 1


def test_stops_at_kernel_modules(tmp_path):
    res = doctor.run(wsl=True, usbipd_text=USBIPD_ATTACHED, dev_glob=str(tmp_path / "none*"),
                     proc_modules=_modules(tmp_path, "uvcvideo 1 0 - Live 0x0\n"))
    names = {r.name: r for r in res}
    assert names["usbipd hand-over"].status == doctor.OK
    assert names["kernel modules"].status == doctor.BROKEN and "vhci-hcd" in names["kernel modules"].fix


def test_identity_missing_preferred(tmp_path):
    res = doctor.run(wsl=False, prefer="dead:beef", dev_glob=_fake_dev(tmp_path), sysfs_root=_fake_sysfs(tmp_path),
                     proc_modules=_modules(tmp_path, "vhci_hcd 1 0\nuvcvideo 1 0\n"))
    names = {r.name: r for r in res}
    assert names["identity"].status == doctor.BROKEN and "32e4:0317" in names["identity"].detail
    assert names["frame delivery"].status == doctor.SKIP


def test_delivery_ok_with_fake_prober(tmp_path):
    def prober(prefer, exclude, ladder, timeout, dev_glob, sysfs_root):
        r = probe.ProbeResult(0)
        r.rungs.append(probe.Rung("MJPG", 640, 480, opened=True, delivered=True, frames=12, seconds=0.5))
        return 0, [r]
    (tmp_path / "proc_empty").mkdir(exist_ok=True)
    res = doctor.run(wsl=False, dev_glob=_fake_dev(tmp_path), sysfs_root=_fake_sysfs(tmp_path),
                     proc_modules=_modules(tmp_path, "vhci_hcd 1 0\nuvcvideo 1 0\n"),
                     proc_root=str(tmp_path / "proc_empty"), prober=prober)
    names = {r.name: r for r in res}
    assert names["frame delivery"].status == doctor.OK and names["frame delivery"].data["fps"] == 24.0
    assert names["stream rate"].status == doctor.SKIP
    assert doctor.exit_code(res) == 0
    txt = doctor.render(res)
    assert "first broken layer" not in txt and "all reachable layers ok" in txt


def test_delivery_broken_names_holder(tmp_path):
    proc = tmp_path / "proc"; (proc / "42" / "fd").mkdir(parents=True)
    (proc / "42" / "comm").write_text("python3"); (proc / "42" / "cmdline").write_bytes(b"python3\0bridge\0")
    os.symlink("/dev/video0", proc / "42" / "fd" / "5")

    def prober(prefer, exclude, ladder, timeout, dev_glob, sysfs_root):
        r = probe.ProbeResult(0)
        r.rungs.append(probe.Rung("MJPG", 640, 480, opened=True, seconds=3.0))
        return None, [r]
    res = doctor.run(wsl=False, dev_glob=_fake_dev(tmp_path), sysfs_root=_fake_sysfs(tmp_path),
                     proc_modules=_modules(tmp_path, "vhci_hcd 1 0\nuvcvideo 1 0\n"),
                     proc_root=str(proc), prober=prober)
    names = {r.name: r for r in res}
    assert names["frame delivery"].status == doctor.BROKEN
    assert names["exclusive openers"].status == doctor.BROKEN and "42" in names["exclusive openers"].detail


def test_probe_skip_without_opencv(tmp_path):
    def prober(*a):
        r = probe.ProbeResult(0); r.error = "opencv not importable; pip install x"
        return None, [r]
    res = doctor.run(wsl=False, dev_glob=_fake_dev(tmp_path), sysfs_root=_fake_sysfs(tmp_path),
                     proc_modules=_modules(tmp_path, "vhci_hcd 1 0\nuvcvideo 1 0\n"), prober=prober)
    names = {r.name: r for r in res}
    assert names["frame delivery"].status == doctor.SKIP and doctor.exit_code(res) == 0


def test_cli_json_smoke(capsys, monkeypatch):
    monkeypatch.setattr(doctor, "run", lambda **k: [doctor.LayerResult("x", doctor.OK, "fine")])
    rc = cli.main(["--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out[0]["name"] == "x"


def test_cli_help_lists_subcommands(capsys):
    try:
        cli.main(["--help"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    for s in ("list", "attach", "probe", "who", "watch", "rtsp"):
        assert s in out
