"""Highlight feed rebuild types, kept out of `types.py` so the workflow sandbox loads only these."""

from pydantic import BaseModel


class RebuildHighlightFeedsInputs(BaseModel, frozen=True):
    pass


class RebuildHighlightFeedsResult(BaseModel, frozen=True):
    built: int = 0
