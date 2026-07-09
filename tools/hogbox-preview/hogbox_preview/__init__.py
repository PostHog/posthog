"""Per-PR PostHog preview environments, layer-agnostic.

backend  = which box (HoglandBackend today, DigitalOceanBackend before)
stack    = what runs in it (PostHogPreviewStack — never changes per layer)

  from hogbox_preview import HoglandBackend, PostHogPreviewStack
  backend = HoglandBackend(host="https://hogland.…ts.net")
  url = PostHogPreviewStack(backend, branch="my-pr").bring_up()
"""

from .backend import ExecResult, PreviewBackend, SSHBackend, SSHTarget
from .digitalocean_backend import DigitalOceanBackend
from .hogland_backend import HoglandBackend
from .stack import PostHogPreviewStack

__all__ = [
    "ExecResult",
    "PreviewBackend",
    "SSHBackend",
    "SSHTarget",
    "HoglandBackend",
    "DigitalOceanBackend",
    "PostHogPreviewStack",
]
