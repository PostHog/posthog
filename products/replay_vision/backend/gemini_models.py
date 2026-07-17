"""Shared Gemini model choice for Replay Vision's interactive AI helpers.

The interactive form helpers — classifier tag suggestions, prompt suggestions, and feedback themes —
each run a single cheap, fast structured call rather than scanning a recording, so they share one model.
Keep it a stable (non-preview) model: preview model ids get retired from the lineup without notice, and a
retired id breaks every helper at once with an opaque API error. Sourcing it from `ScannerModel` means a
future retirement of this tier surfaces as a visible enum change rather than a silent outage.
"""

from products.replay_vision.backend.models.replay_scanner import ScannerModel

# Cheap stable tier — the model that retired Lite scanners were remapped to (see migration 0035).
INTERACTIVE_HELPER_MODEL: str = ScannerModel.GEMINI_2_5_FLASH.value
