"""Layer 7: does the network camera SERVE, in the protocol's own words.

`ping` proves the device's network stack is alive and says NOTHING about the
camera behind it. On the rig both arms answered ping and served HTTP 200 in
86 ms while one wrist camera's RTSP server was wedged. The vision driver then
retried for ever and published a topic with no frames on it.

WHY NOT GStreamer. The first probe here was

    gst-launch-1.0 rtspsrc location=rtsp://IP/color protocols=tcp ! fakesink

and it failed on a HEALTHY camera every time: `rtspsrc` exposes its pads
dynamically once the stream is described, so that pipeline can never link
statically and never reaches PLAYING whatever the server does. It refused to
start a camera that was answering perfectly -- a gate inventing the fault it
was written to detect. A CHECK THAT CANNOT PASS IS WORSE THAN NO CHECK. Prove
a new probe against a known-good device before trusting a negative.

So ask RTSP itself: OPTIONS, then DESCRIBE, over TCP. A server that answers
DESCRIBE with an SDP containing a video track is serving. One that accepts
the connection and never replies is the wedged vision module, which does not
recover on its own and needs the device power-cycled.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass


@dataclass
class RtspResult:
    ok: bool
    status: str        # short machine-friendly code
    detail: str
    fps: str = "?"


def _request(sock: socket.socket, method: str, url: str, cseq: int, extra: str = "") -> None:
    sock.sendall(("%s %s RTSP/1.0\r\nCSeq: %d\r\nUser-Agent: camera-doctor\r\n%s\r\n"
                  % (method, url, cseq, extra)).encode())


def _recv(sock: socket.socket, n: int) -> str | None:
    try:
        data = sock.recv(n)
    except socket.timeout:
        return None
    return data.decode("utf-8", "replace")


def parse_sdp(sdp: str) -> tuple[bool, str]:
    """(has video track, framerate or '?')"""
    has_video = any(line.startswith("m=video") for line in sdp.splitlines())
    fps = "?"
    for line in sdp.splitlines():
        if line.startswith("a=framerate:"):
            fps = line.split(":", 1)[1].strip()
    return has_video, fps


def probe(ip: str, path: str = "/color", port: int = 554, timeout: float = 6.0) -> RtspResult:
    url = "rtsp://%s:%d%s" % (ip, port, path) if port != 554 else "rtsp://%s%s" % (ip, path)
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return RtspResult(False, "no-tcp", "no TCP connection to %s:%d (%s)" % (ip, port, e))
    with s:
        s.settimeout(timeout)
        try:
            _request(s, "OPTIONS", url, 1)
            head = _recv(s, 2048)
            if head is None or not head:
                return RtspResult(False, "wedged",
                                  "connected to %s:%d and got NO REPLY to OPTIONS: the vision "
                                  "module is wedged. It does not recover on its own; "
                                  "power-cycle the device." % (ip, port))
            first = head.splitlines()[0] if head.splitlines() else ""
            if "200" not in first:
                return RtspResult(False, "options-refused", "OPTIONS refused: %s" % first)
            _request(s, "DESCRIBE", url, 2, "Accept: application/sdp\r\n")
            sdp = _recv(s, 16384)
            if sdp is None or not sdp:
                return RtspResult(False, "describe-unanswered",
                                  "answered OPTIONS but NOT DESCRIBE: the server is up and the "
                                  "camera behind it is not")
            first = sdp.splitlines()[0] if sdp.splitlines() else ""
            if "200" not in first:
                return RtspResult(False, "describe-refused", "DESCRIBE refused: %s" % first)
            has_video, fps = parse_sdp(sdp)
            if not has_video:
                return RtspResult(False, "no-video", "DESCRIBE returned no video track")
            return RtspResult(True, "serving", "serving %s at %s fps" % (url, fps), fps)
        except OSError as e:
            return RtspResult(False, "socket-error", "socket error talking RTSP: %s" % e)
