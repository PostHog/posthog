"""Shared types for stage envelopes.

Each stage column on `FounderProject` carries an envelope with a `status` field. Defining
the `StageStatus` literal once here avoids drf-spectacular generating multiple identical
`pending|running|completed|failed` enums and emitting "multiple names for the same choice
set" warnings on the OpenAPI build.
"""

from typing import Literal

StageStatus = Literal["pending", "running", "completed", "failed"]
