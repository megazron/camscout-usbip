"""camscout-usbip: name the broken layer between a camera and a robot stack.

Every camera fault looks the same from the top: a node burning CPU, a topic
with one publisher, and a blank panel. This package walks the layers in order
(Windows usbipd hand-over, kernel modules, device identity, frame delivery,
exclusive openers, stream rate, RTSP) and stops at the first one that is wrong.
"""
from .doctor import LayerResult, run  # noqa: F401
from .probe import deliver, select_camera  # noqa: F401
from .ratemeter import RateMeter  # noqa: F401
from .rtsp import probe as rtsp_probe  # noqa: F401
from .usbipd import attach_commands, parse_usbipd_list  # noqa: F401
from .v4l2 import group_by_device, identity, video_nodes  # noqa: F401

__version__ = "0.1.0"
