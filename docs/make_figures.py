#!/usr/bin/env python3
"""Regenerate every figure in docs/img.

    python3 docs/make_figures.py

Diagrams are written as hand-built SVG (no dependency). The probe-ladder table
is drawn with matplotlib if it is installed, otherwise skipped with a note.
`layers.svg` embeds the doctor's real output on the machine that runs this
script, so re-running it on another box shows that box's first broken layer.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "img")
SRC = os.path.join(os.path.dirname(HERE), "src")
os.makedirs(IMG, exist_ok=True)

INK, MUTED, LINE = "#1f2937", "#6b7280", "#d1d5db"
BLUE, BLUE_BG = "#2563eb", "#eff6ff"
GREEN, GREEN_BG = "#15803d", "#ecfdf5"
AMBER, AMBER_BG = "#b45309", "#fffbeb"
RED, RED_BG = "#b91c1c", "#fef2f2"
GREY_BG = "#f3f4f6"
SANS = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', Consolas, 'Courier New', monospace"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SVG:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'font-family="{SANS}" font-size="13" fill="{INK}">',
            '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0 0L10 5L0 10z" fill="{MUTED}"/></marker>'
            '<marker id="arrb" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0 0L10 5L0 10z" fill="{BLUE}"/></marker></defs>',
            f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        ]

    def box(self, x, y, w, h, fill="#fff", stroke=LINE, r=6, sw=1.2, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, size=13, weight="normal", fill=INK, anchor="start", mono=False, italic=False):
        fam = MONO if mono else SANS
        st = ' font-style="italic"' if italic else ""
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" font-family="{fam}"{st}>{esc(s)}</text>')

    def lines(self, x, y, rows, size=12, lh=16, **kw):
        for i, s in enumerate(rows):
            self.text(x, y + i * lh, s, size=size, **kw)

    def arrow(self, x1, y1, x2, y2, color=MUTED, blue=False, dash=None, sw=1.5):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        m = "arrb" if blue else "arr"
        self.parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}" marker-end="url(#{m})"{d}/>')

    def path(self, d, color=MUTED, sw=1.5, dash=None, arrow=True):
        dd = f' stroke-dasharray="{dash}"' if dash else ""
        m = ' marker-end="url(#arr)"' if arrow else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{dd}{m}/>')

    def badge(self, x, y, n, color=RED):
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="10" fill="{color}"/>')
        self.text(x, y + 4, str(n), size=11, weight="bold", fill="#fff", anchor="middle")

    def pill(self, x, y, s, color, bg, size=11):
        w = int(len(s) * size * 0.62 + 16)
        self.box(x, y - 13, w, 20, fill=bg, stroke=color, r=10)
        self.text(x + w / 2, y + 1, s, size=size, weight="bold", fill=color, anchor="middle")
        return w

    def save(self, name):
        self.parts.append("</svg>")
        with open(os.path.join(IMG, name), "w") as f:
            f.write("\n".join(self.parts))
        print("wrote", name)


def real_run():
    """The doctor's own output on this machine, or the recorded one."""
    try:
        p = subprocess.run([sys.executable, "-m", "usbip_camera_doctor.cli"], capture_output=True,
                           text=True, timeout=120, env={**os.environ, "PYTHONPATH": SRC})
        out = (p.stdout or "").strip()
        if "CAMERA DOCTOR" in out:
            return out.splitlines()
    except Exception:  # noqa: BLE001
        pass
    return RECORDED.splitlines()


RECORDED = """== CAMERA DOCTOR == (laptop, WSL)
  usbipd hand-over   BROKEN       Windows sees 'HP 5MP Camera' (30c9:00c1, busid 2-5) but it is Not shared, not Attached
                                  fix: usbipd bind --busid 2-5; usbipd attach --wsl --busid 2-5
  kernel modules     SKIP         not reached: a lower layer is broken
  video devices      SKIP         not reached: a lower layer is broken
  identity           SKIP         not reached: a lower layer is broken
  frame delivery     SKIP         not reached: a lower layer is broken
  exclusive openers  SKIP         not reached: a lower layer is broken
  stream rate        SKIP         not reached: a lower layer is broken

verdict: first broken layer is 'usbipd hand-over'"""


# ------------------------------------------------------------------ layers
def layers():
    W, H = 1080, 600
    s = SVG(W, H)
    s.text(24, 34, "Seven layers, walked in order. The doctor stops at the first one that is broken.", size=16, weight="bold")
    s.text(24, 54, "A fault low down makes every answer above it meaningless, so nothing above the break is reported as healthy.", size=12, fill=MUTED)
    steps = [
        ("1  usbipd hand-over", "Windows must bind (admin, once) and attach (each session) the device to WSL"),
        ("2  kernel modules", "vhci-hcd and uvcvideo loaded; otherwise usbipd says Attached and Linux has no /dev/video*"),
        ("3  /dev/video* present", "a capture node exists at all"),
        ("4  identity by VID:PID", "the node is the camera you meant; the index is not an identity, it renumbers on re-attach"),
        ("5  frame delivery", "opens is not delivers: read a frame, MJPG 640x480 first, then 720p, then YUYV"),
        ("6  exclusive openers", "a V4L2 device cannot be opened twice for capture; the loser silently gets nothing"),
        ("7  stream rate and gaps", "achieved Hz and the longest gap against a stale threshold"),
    ]
    x, y0, bw, bh, gap = 24, 78, 470, 56, 12
    for i, (t, d) in enumerate(steps):
        y = y0 + i * (bh + gap)
        broken = i == 0
        s.box(x, y, bw, bh, fill=RED_BG if broken else (GREY_BG if i else "#fff"), stroke=RED if broken else LINE, sw=1.6 if broken else 1.2)
        s.text(x + 14, y + 22, t, size=13, weight="bold", fill=RED if broken else INK)
        # wrap description at ~72 chars
        words, line, rows = d.split(), "", []
        for wd in words:
            if len(line) + len(wd) + 1 > 74:
                rows.append(line); line = wd
            else:
                line = (line + " " + wd).strip()
        rows.append(line)
        s.lines(x + 14, y + 40, rows[:2], size=11, lh=13, fill=MUTED)
        if i < len(steps) - 1:
            s.arrow(x + bw / 2, y + bh, x + bw / 2, y + bh + gap - 1)
    # stop marker
    s.pill(x + bw + 12, y0 + 28, "STOP HERE", RED, RED_BG)
    s.text(x + bw + 12, y0 + 56, "verdict names this layer", size=11, fill=RED)
    s.text(x + bw + 12, y0 + 72, "and prints the exact fix", size=11, fill=RED)
    for i in range(1, 7):
        y = y0 + i * (bh + gap)
        s.text(x + bw + 12, y + 33, "SKIP  not reached", size=11, fill=MUTED, mono=True)

    # terminal panel with the real run
    tx, ty, tw, th = 640, 78, 416, 464
    s.box(tx, ty, tw, th, fill="#0b1220", stroke="#0b1220", r=8)
    s.parts.append(f'<circle cx="{tx+16}" cy="{ty+16}" r="5" fill="#ef4444"/><circle cx="{tx+32}" cy="{ty+16}" r="5" fill="#f59e0b"/><circle cx="{tx+48}" cy="{ty+16}" r="5" fill="#22c55e"/>')
    s.text(tx + tw / 2, ty + 20, "$ camera-doctor      (this machine)", size=11, fill="#94a3b8", anchor="middle", mono=True)
    rows = real_run()
    yy = ty + 46
    for r in rows:
        col = "#e5e7eb"
        if "BROKEN" in r: col = "#f87171"
        elif "SKIP" in r: col = "#64748b"
        elif "fix:" in r: col = "#fbbf24"
        elif "verdict" in r: col = "#f87171"
        elif r.startswith("=="): col = "#93c5fd"
        # wrap long lines
        chunk = 58
        rr = r
        first = True
        while rr or first:
            piece, rr = rr[:chunk], rr[chunk:]
            s.text(tx + 12, yy, piece, size=9.5, fill=col, mono=True)
            yy += 13
            first = False
            if yy > ty + th - 10:
                break
        if yy > ty + th - 10:
            break
    s.text(tx, ty + th + 22, "Real output. Layers above the break are reported SKIP, never healthy.", size=11, fill=MUTED, italic=True)
    s.save("layers.svg")


# ---------------------------------------------------------------- topology
def topology():
    W, H = 1160, 560
    s = SVG(W, H)
    s.text(24, 34, "Where a camera frame travels, and the five places it silently stops", size=16, weight="bold")
    s.text(24, 54, "Every one of these presents the same way: a node at 20-30% CPU, Publisher count 1, and a blank panel.", size=12, fill=MUTED)
    y, h = 140, 74
    nodes = [
        (24, 140, "Windows", ["USB camera", "VID:PID 32e4:0317"]),
        (190, 150, "usbipd-win", ["bind  (admin, once)", "attach (each session)"]),
        (368, 150, "WSL2 kernel", ["vhci-hcd + uvcvideo", "modules, not loaded by default"]),
        (546, 170, "/dev/videoN", ["RealSense: six nodes, one colour", "webcam: capture + metadata"]),
        (744, 140, "camera node", ["MJPG 640x480", "read, do not just open"]),
        (912, 120, "ROS 2 topic", ["BEST_EFFORT", "sensor QoS"]),
        (1060, 76, "subscriber", ["GUI, detector"]),
    ]
    for i, (x, w, t, d) in enumerate(nodes):
        s.box(x, y, w, h, fill=BLUE_BG if i in (1, 4) else "#fff", stroke=BLUE if i in (1, 4) else LINE)
        s.text(x + w / 2, y + 24, t, size=13, weight="bold", anchor="middle")
        s.lines(x + w / 2, y + 42, d, size=10.5, lh=13, fill=MUTED, anchor="middle")
        if i < len(nodes) - 1:
            nx = nodes[i + 1][0]
            s.arrow(x + w + 2, y + h / 2, nx - 2, y + h / 2)
    # failure markers
    fails = [
        (1, 510, "stale /dev/shm segments", "publisher decodes, subscriber gets nothing", "see ros2-wsl-doctor"),
        (2, 1000, "QoS mismatch", "RELIABLE subscriber vs BEST_EFFORT publisher", "ros2 topic hz also gets zero"),
        (3, 720, "two openers of one device", "first to start wins, the other reads nothing", "camera-doctor who /dev/videoN"),
        (4, 330, "wedged RTSP vision module", "ping and HTTP 200 still pass", "camera-doctor rtsp IP"),
        (5, 880, "a probe that lies", "gst rtspsrc ! fakesink can never link", "prove a probe on a known-good device"),
    ]
    for n, x, t, d, f in fails:
        pass
    # markers on the chain
    s.badge(734, y - 8, 3)          # between /dev/video and node
    s.badge(903, y - 8, 1)          # topic side (shm)
    s.badge(1050, y - 8, 2)         # subscriber (qos)
    # legend
    lx, ly = 24, 268
    s.text(lx, ly, "The five silent failures", size=13, weight="bold")
    for k, (n, _, t, d, f) in enumerate(fails):
        yy = ly + 24 + k * 44
        s.badge(lx + 10, yy - 4, n)
        s.text(lx + 30, yy, t, size=12, weight="bold")
        s.text(lx + 30, yy + 15, d + "   ·   " + f, size=11, fill=MUTED)
    # RTSP side path
    rx, ry = 700, 300
    s.text(rx, ry, "The wrist cameras are not USB at all", size=13, weight="bold")
    s.box(rx, ry + 14, 150, 62, fill="#fff")
    s.text(rx + 75, ry + 38, "arm (Kinova Gen3)", size=12, weight="bold", anchor="middle")
    s.text(rx + 75, ry + 56, "vision module, RTSP :554", size=10.5, fill=MUTED, anchor="middle")
    s.arrow(rx + 152, ry + 45, rx + 238, ry + 45)
    s.text(rx + 195, ry + 38, "TCP", size=10, fill=MUTED, anchor="middle")
    s.box(rx + 240, ry + 14, 170, 62, fill="#fff")
    s.text(rx + 325, ry + 38, "kinova_vision node", size=12, weight="bold", anchor="middle")
    s.text(rx + 325, ry + 56, "retries for ever if wedged", size=10.5, fill=MUTED, anchor="middle")
    s.badge(rx + 195, ry + 66, 4)
    s.badge(rx + 195, ry + 92, 5)
    s.text(rx + 212, ry + 96, "the first probe reported a healthy camera as dead", size=10.5, fill=MUTED)
    s.path(f"M{rx+410} {ry+45} C {rx+440} {ry+45} {rx+440} {y+h+20} {912+60} {y+h+2}", dash="4 4")
    s.text(rx + 300, ry + 140, "Ping proves the arm's network stack. It says nothing about the camera behind it.", size=11, fill=MUTED, italic=True)
    s.text(24, H - 20, "Fix order is the layer order: hand-over, modules, device, identity, delivery, openers, rate. Then QoS on the subscriber side.", size=11, fill=MUTED)
    s.save("topology.svg")


# ------------------------------------------------------------- rtsp states
def rtsp_states():
    W, H = 1080, 440
    s = SVG(W, H)
    s.text(24, 34, "Asking RTSP itself: OPTIONS, then DESCRIBE, over TCP on port 554", size=16, weight="bold")
    s.text(24, 54, "Five outcomes that ping, HTTP 200 and kinova_vision's own log cannot tell apart.", size=12, fill=MUTED)
    # chain
    cx, cy = 24, 110
    s.box(cx, cy, 130, 54, fill=BLUE_BG, stroke=BLUE); s.text(cx + 65, cy + 24, "TCP connect", size=12, weight="bold", anchor="middle"); s.text(cx + 65, cy + 42, "IP:554, 6 s", size=10.5, fill=MUTED, anchor="middle")
    s.arrow(cx + 132, cy + 27, cx + 208, cy + 27, blue=True)
    s.box(cx + 210, cy, 130, 54, fill=BLUE_BG, stroke=BLUE); s.text(cx + 275, cy + 24, "OPTIONS", size=12, weight="bold", anchor="middle"); s.text(cx + 275, cy + 42, "expect 200 OK", size=10.5, fill=MUTED, anchor="middle")
    s.arrow(cx + 342, cy + 27, cx + 418, cy + 27, blue=True)
    s.box(cx + 420, cy, 130, 54, fill=BLUE_BG, stroke=BLUE); s.text(cx + 485, cy + 24, "DESCRIBE", size=12, weight="bold", anchor="middle"); s.text(cx + 485, cy + 42, "expect an SDP", size=10.5, fill=MUTED, anchor="middle")
    s.arrow(cx + 552, cy + 27, cx + 628, cy + 27, blue=True)
    s.box(cx + 630, cy, 150, 54, fill=GREEN_BG, stroke=GREEN); s.text(cx + 705, cy + 24, "SERVING", size=12, weight="bold", fill=GREEN, anchor="middle"); s.text(cx + 705, cy + 42, "m=video, a=framerate:N", size=10.5, fill=MUTED, anchor="middle")
    # failure outcomes below each stage
    outs = [
        (cx + 65, "no TCP connection", "wrong IP, arm off, or port closed", RED),
        (cx + 275, "connected, no reply", "the vision module is WEDGED; power-cycle the arm, it does not recover", RED),
        (cx + 485, "OPTIONS ok, DESCRIBE silent", "server up, camera behind it not", AMBER),
        (cx + 705, "SDP without m=video", "wrong path or no video track", AMBER),
    ]
    for x, t, d, col in outs:
        s.arrow(x, cy + 56, x, cy + 108, color=col, dash="3 3")
        s.box(x - 78, cy + 110, 156, 64, fill=RED_BG if col == RED else AMBER_BG, stroke=col)
        s.text(x, cy + 132, t, size=11.5, weight="bold", fill=col, anchor="middle")
        words, line, rows = d.split(), "", []
        for wd in words:
            if len(line) + len(wd) + 1 > 26:
                rows.append(line); line = wd
            else:
                line = (line + " " + wd).strip()
        rows.append(line)
        s.lines(x, cy + 148, rows[:2], size=10, lh=12, fill=MUTED, anchor="middle")
    # contrast panel
    px, py = 24, 320
    s.box(px, py, 1032, 92, fill=GREY_BG, stroke=LINE)
    s.text(px + 16, py + 24, "What does NOT tell you the camera works", size=12.5, weight="bold")
    s.lines(px + 16, py + 44, [
        "ping IP            proves the arm's network stack only. Both arms answered ping while one RTSP server was wedged.",
        "HTTP 200 in 86 ms  same: the web server is not the vision module.",
        "gst-launch rtspsrc ! fakesink   can never reach PLAYING (rtspsrc has dynamic pads). It reported a healthy camera as broken and blocked it.",
    ], size=10.5, lh=15, mono=True, fill=INK)
    s.text(px + 16, py + 84 + 4, "", size=10)
    s.text(24, H - 12, "A check that cannot pass is worse than no check. Prove a new probe against a known-good device before trusting a negative.", size=11, fill=MUTED, italic=True)
    s.save("rtsp_states.svg")


# ------------------------------------------------------------ probe ladder
def probe_ladder():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping probe_ladder.png")
        return
    rows = [
        ("MJPG", "640 x 480", "delivers", "24.9 fps on the HD webcam; 13.9 Hz RealSense colour; the ladder's first rung", GREEN),
        ("MJPG", "1280 x 720", "opens, no frame", "over usbip the RealSense delivers nothing at 720p; and a raw 720p Image exceeds the default FastDDS SHM segment, so it never reaches a subscriber", AMBER),
        ("YUYV", "640 x 480", "opens, select() timeout", "default format negotiates fine and then never returns a frame; indistinguishable from a camera that sees nothing", RED),
        ("any", "RealSense via usbip", "~5 Hz, gaps to 0.93 s", "a 0.5 s stale threshold flickers STALE while the node reports no dropout; use 1.2-1.5 s", AMBER),
        ("any", "depth/IR/meta node", "opens, never delivers", "the RealSense presents six identically named /dev/video* nodes; only one carries colour", RED),
    ]
    fig, ax = plt.subplots(figsize=(11, 3.9), dpi=150)
    ax.axis("off")
    ax.set_title("The probe ladder: a read, not an open", loc="left", fontsize=13, fontweight="bold", pad=14)
    colx = [0.0, 0.09, 0.26, 0.47]
    heads = ["fourcc", "resolution", "outcome", "measured on the rig"]
    for x, h_ in zip(colx, heads):
        ax.text(x, 1.0, h_, fontsize=10, fontweight="bold", va="top", transform=ax.transAxes, color="#374151")
    ax.plot([0, 1], [0.955, 0.955], color="#d1d5db", lw=1, transform=ax.transAxes)
    import textwrap
    y = 0.90
    for f, r, o, d, col in rows:
        ax.text(colx[0], y, f, fontsize=10, family="monospace", va="top", transform=ax.transAxes)
        ax.text(colx[1], y, r, fontsize=10, va="top", transform=ax.transAxes)
        ax.text(colx[2], y, o, fontsize=10, fontweight="bold", va="top", color=col, transform=ax.transAxes)
        wrapped = textwrap.fill(d, 78)
        ax.text(colx[3], y, wrapped, fontsize=9, va="top", color="#4b5563", transform=ax.transAxes, linespacing=1.3)
        y -= 0.19 if "\n" in wrapped else 0.14
    ax.text(0, -0.02, "Rule: a device that opens is not a device that delivers. Try MJPG 640x480 first, time-box the read, and report every node you rejected and why.",
            fontsize=9, style="italic", color="#6b7280", va="top", transform=ax.transAxes)
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, "probe_ladder.png"), bbox_inches="tight", facecolor="white")
    print("wrote probe_ladder.png")


if __name__ == "__main__":
    layers(); topology(); rtsp_states(); probe_ladder()
