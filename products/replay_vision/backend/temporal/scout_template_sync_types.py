"""Scout template sync types, kept out of `types.py` so the workflow sandbox loads only these."""

from pydantic import BaseModel


class SyncScoutTemplatesInputs(BaseModel, frozen=True):
    pass


class SyncScoutTemplatesResult(BaseModel, frozen=True):
    updated: int = 0
    claimed: int = 0
    edited: int = 0
    failed: int = 0
