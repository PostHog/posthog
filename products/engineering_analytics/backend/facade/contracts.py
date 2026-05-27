"""Contract types for engineering_analytics.

Canonical data model — Author, RepoRef, PRState, WorkflowConclusion,
PullRequest, WorkflowRun — plus the tool-specific return types
(WorkflowReport, TimeToMerge, PRLifecycle). Added with the MCP tools
vertical-slice PR. See SPEC.md section 4.

Types use `pydantic.dataclasses.dataclass(frozen=True)`: same `is_dataclass()`
semantics as the stdlib variant (so `DataclassSerializer` keeps working) but
with runtime validation at construction, so structural mistakes from mappers
surface at the facade boundary rather than as a malformed JSON payload
twelve stack frames later.

This file is intentionally empty in PR 1. Keeping it present (rather than
deleting) preserves `is_isolated_product = True` for `hogli product:lint`
and matches the contract-input glob in the root turbo.json.
"""
