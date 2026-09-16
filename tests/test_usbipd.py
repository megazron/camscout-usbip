from usbip_camera_doctor import usbipd

SAMPLE = """Connected:
BUSID  VID:PID    DEVICE                                                        STATE
2-9    32e4:0317  HD USB CAMERA, HD USB CAMERA                                  Shared
3-3    8086:0b3a  Intel(R) RealSense(TM) Depth Camera 435i                      Attached
3-2    046d:c52b  USB Input Device, Logitech USB Input Device                   Not shared
1-4    16c0:0483  USB Serial Device (COM5)                                      Attached
2-10   1a2b:3c4d  Some Hub Thing                                                Shared (forced)

Persisted:
GUID                                  DEVICE
a1b2c3d4-0000-0000-0000-000000000000  HD USB CAMERA
"""


def test_parse_rows():
    devs = usbipd.parse_usbipd_list(SAMPLE)
    assert [d.busid for d in devs] == ["2-9", "3-3", "3-2", "1-4", "2-10"]
    cam = devs[0]
    assert cam.vidpid == "32e4:0317" and cam.state == "Shared" and cam.shared and not cam.attached
    assert devs[1].attached and devs[1].shared
    assert devs[2].state == "Not shared" and not devs[2].shared
    assert devs[4].state == "Shared (forced)" and devs[4].shared
    assert "HD USB CAMERA" in cam.description


def test_persisted_section_ignored():
    devs = usbipd.parse_usbipd_list(SAMPLE)
    assert all(d.busid != "GUID" for d in devs)
    assert len(devs) == 5


def test_find_by_vidpid_and_name():
    devs = usbipd.parse_usbipd_list(SAMPLE)
    assert [d.busid for d in usbipd.find(devs, vidpid="8086:0B3A")] == ["3-3"]
    assert [d.busid for d in usbipd.find(devs, name_regex="realsense")] == ["3-3"]
    assert usbipd.find(devs, vidpid="dead:beef") == []


def test_attach_commands_per_state():
    ns = usbipd.attach_commands("2-9", "Not shared")
    assert [c for c, _ in ns] == ["usbipd bind --busid 2-9", "usbipd attach --wsl --busid 2-9"]
    assert "ADMINISTRATOR" in ns[0][1]
    sh = usbipd.attach_commands("2-9", "Shared")
    assert [c for c, _ in sh] == ["usbipd attach --wsl --busid 2-9"]
    assert usbipd.attach_commands("2-9", "Attached") == []
