"""Learned-rules-only types, kept out of `types.py` so the workflow sandbox loads only these."""

from pydantic import BaseModel


class RefreshLearnedRulesInputs(BaseModel, frozen=True):
    pass


class RefreshTeamLearnedRulesInputs(BaseModel, frozen=True):
    team_id: int


class RefreshLearnedRulesResult(BaseModel, frozen=True):
    refreshed: list[int] = []
    skipped: list[int] = []
    failed: list[int] = []
