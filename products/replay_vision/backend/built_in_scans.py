"""Inline scans PostHog defines itself, run by name rather than by a caller's prompt.

The app's Summarize button is one. Because the backend owns its prompt and question, every caller that
asks for it by name lands on the same inline scanner and sees the same written question.
"""

from typing import Any

from django.db import models

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_scanner import PromptValence, ScannerType


class BuiltInScanKey(models.TextChoices):
    SUMMARIZE_RECORDING = "summarize_recording", "Summarize recording"


@frozen
class BuiltInScan:
    scanner_type: ScannerType
    prompt: str
    length: str
    question: str
    valence: PromptValence

    def scanner_config(self) -> dict[str, Any]:
        """A fresh copy each call, because the caller stores it on the scanner it creates."""
        return {"length": self.length, "prompt": self.prompt}


BUILT_IN_SCANS: dict[str, BuiltInScan] = {
    # pinned: the inline scanner is keyed by a fingerprint of this type and config, so any edit here starts a
    # new scanner in every project and leaves the summaries made so far on the old one.
    BuiltInScanKey.SUMMARIZE_RECORDING: BuiltInScan(
        scanner_type=ScannerType.SUMMARIZER,
        prompt="Summarize what the user did in this session: which pages they visited, what they tried to accomplish, and any notable moments like errors, confusion, or successful completions. Be concrete and don't speculate.",
        length="medium",
        question="What did the user do in this session?",
        valence=PromptValence.NEUTRAL,
    ),
}


def built_in_scan_for(scanner_type: str, scanner_config: object) -> BuiltInScan | None:
    """The built-in scan this exact type and config run, or None for any other."""
    for scan in BUILT_IN_SCANS.values():
        if scanner_type == scan.scanner_type and scanner_config == scan.scanner_config():
            return scan
    return None
