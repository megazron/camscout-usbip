import socket
import threading

import pytest

from usbip_camera_doctor import rtsp

SDP = ("v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=cam\r\nm=video 0 RTP/AVP 96\r\n"
       "a=framerate:30.0\r\na=rtpmap:96 H264/90000\r\n")


def serve(mode):
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]

    def run():
        conn, _ = srv.accept()
        conn.settimeout(5)
        try:
            if mode == "wedged":
                threading.Event().wait(3.0)
                return
            conn.recv(4096)  # OPTIONS
            conn.sendall(b"RTSP/1.0 200 OK\r\nCSeq: 1\r\nPublic: OPTIONS, DESCRIBE\r\n\r\n")
            if mode == "describe-silent":
                threading.Event().wait(3.0)
                return
            conn.recv(4096)  # DESCRIBE
            body = SDP if mode == "ok" else "v=0\r\nm=audio 0 RTP/AVP 0\r\n"
            conn.sendall(("RTSP/1.0 200 OK\r\nCSeq: 2\r\nContent-Type: application/sdp\r\n"
                          "Content-Length: %d\r\n\r\n%s" % (len(body), body)).encode())
        finally:
            try:
                conn.close()
            except OSError:
                pass
            srv.close()
    threading.Thread(target=run, daemon=True).start()
    return port


def test_serving():
    r = rtsp.probe("127.0.0.1", port=serve("ok"), timeout=2)
    assert r.ok and r.status == "serving" and r.fps == "30.0"


def test_wedged_no_reply():
    r = rtsp.probe("127.0.0.1", port=serve("wedged"), timeout=1)
    assert not r.ok and r.status == "wedged" and "power-cycle" in r.detail


def test_describe_unanswered():
    r = rtsp.probe("127.0.0.1", port=serve("describe-silent"), timeout=1)
    assert not r.ok and r.status == "describe-unanswered"


def test_no_video_track():
    r = rtsp.probe("127.0.0.1", port=serve("novideo"), timeout=2)
    assert not r.ok and r.status == "no-video"


def test_refused():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    r = rtsp.probe("127.0.0.1", port=port, timeout=1)
    assert not r.ok and r.status == "no-tcp"


def test_parse_sdp():
    assert rtsp.parse_sdp(SDP) == (True, "30.0")
    assert rtsp.parse_sdp("m=audio 0\r\n") == (False, "?")
