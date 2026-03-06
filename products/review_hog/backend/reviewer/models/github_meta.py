#!/usr/bin/env python3

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PRMetadata(BaseModel):
    number: int
    title: str
    body: str = ""
    state: str
    draft: bool
    created_at: str
    updated_at: str
    author: str
    author_association: str = "NONE"
    base_branch: str
    head_branch: str
    mergeable_state: str | None = None
    requested_reviewers: list[str] = Field(default_factory=list)
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)
    commits: int
    additions: int
    deletions: int
    changed_files: int


class PRComment(BaseModel):
    path: str
    line: int | None = None
    start_line: int | None = None
    body: str
    diff_hunk: str
    user: str
    created_at: str


class PRFileUpdate(BaseModel):
    type: str  # "addition", "deletion", or "context"
    old_start_line: int | None = None
    old_end_line: int | None = None
    new_start_line: int | None = None
    new_end_line: int | None = None
    code: str


class PRFile(BaseModel):
    filename: str
    status: str
    additions: int
    deletions: int
    changes: list[PRFileUpdate] = Field(default_factory=list)
