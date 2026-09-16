import os

from usbip_camera_doctor import v4l2


def fake_sysfs(tmp_path, devices):
    """devices: list of (vid, pid, name, [indices]). Builds a sysfs-like tree with symlinks."""
    root = tmp_path / "class" / "video4linux"
    root.mkdir(parents=True)
    for k, (vid, pid, name, idxs) in enumerate(devices):
        usb = tmp_path / "devices" / ("usb%d" % k)
        (usb).mkdir(parents=True)
        (usb / "idVendor").write_text(vid + "\n")
        (usb / "idProduct").write_text(pid + "\n")
        for i in idxs:
            node = usb / ("1-%d:1.0" % k) / "video4linux" / ("video%d" % i)
            node.mkdir(parents=True)
            (node / "name").write_text(name + "\n")
            os.symlink(node, root / ("video%d" % i))
    return str(root)


def test_identity_reads_name_and_vidpid(tmp_path):
    root = fake_sysfs(tmp_path, [("32e4", "0317", "HD USB CAMERA: HD USB CAMERA", [0, 1])])
    n = v4l2.identity(0, root)
    assert n.name.startswith("HD USB CAMERA") and n.vidpid == "32e4:0317" and n.dev == "/dev/video0"


def test_identity_missing_node(tmp_path):
    root = fake_sysfs(tmp_path, [])
    n = v4l2.identity(7, root)
    assert n.name == "" and n.vidpid == ""


def test_group_realsense_six_nodes(tmp_path):
    root = fake_sysfs(tmp_path, [("8086", "0b3a", "Intel(R) RealSense(TM) Depth Ca", [2, 3, 4, 5, 6, 7]),
                                 ("32e4", "0317", "HD USB CAMERA", [0, 1])])
    nodes = [v4l2.identity(i, root) for i in range(8)]
    devs = v4l2.group_by_device(nodes)
    assert len(devs) == 2
    by = {d.vidpid: d for d in devs}
    assert [n.index for n in by["8086:0b3a"].nodes] == [2, 3, 4, 5, 6, 7]
    assert [n.index for n in by["32e4:0317"].nodes] == [0, 1]


def test_modules_detection():
    text = "uvcvideo 118784 0 - Live 0x0000000000000000\nvideobuf2_v4l2 36864 1 uvcvideo, Live 0x0\n"
    loaded = v4l2.parse_modules(text)
    assert v4l2.missing_modules(loaded) == ["vhci_hcd"]
    assert v4l2.modprobe_fix(["vhci_hcd", "uvcvideo"]) == "sudo modprobe vhci-hcd uvcvideo"
    assert v4l2.missing_modules(v4l2.parse_modules(text + "vhci_hcd 40960 0 - Live 0x0\n")) == []


def test_missing_proc_modules_is_empty(tmp_path):
    assert v4l2.loaded_modules(str(tmp_path / "nope")) == set()
