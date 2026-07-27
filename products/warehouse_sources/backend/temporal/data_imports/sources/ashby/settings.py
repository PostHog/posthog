from dataclasses import dataclass
from typing import Optional


@dataclass
class AshbyEndpointConfig:
    name: str
    """Table name we expose to the user (snake_case)."""
    path: str
    """Ashby RPC method, e.g. ``candidate.list`` (called as POST ``/<path>``)."""
    primary_key: list[str]
    partition_key: Optional[str] = None
    """A STABLE creation-time field to partition on. ``None`` disables partitioning.

    Only set where the object is documented to carry a top-level ``createdAt`` — never a
    mutable field like ``updatedAt`` (partitions would rewrite on every sync).
    """


# Every Ashby object exposes a top-level ``id``, so the primary key is ``["id"]`` throughout.
#
# Incremental sync is intentionally not advertised: Ashby's only incremental mechanisms are an
# opaque ``syncToken`` (which does not map onto PostHog's timestamp-watermark model) and a
# ``createdAfter`` filter whose list endpoints provide no documented ordering guarantee — a
# watermark-based sync could silently skip rows. We ship full refresh; see source.py / the PR
# for the syncToken follow-up.
ASHBY_ENDPOINTS: dict[str, AshbyEndpointConfig] = {
    "candidates": AshbyEndpointConfig(
        name="candidates", path="candidate.list", primary_key=["id"], partition_key="createdAt"
    ),
    "applications": AshbyEndpointConfig(
        name="applications", path="application.list", primary_key=["id"], partition_key="createdAt"
    ),
    "jobs": AshbyEndpointConfig(name="jobs", path="job.list", primary_key=["id"], partition_key="createdAt"),
    "job_postings": AshbyEndpointConfig(name="job_postings", path="jobPosting.list", primary_key=["id"]),
    "offers": AshbyEndpointConfig(name="offers", path="offer.list", primary_key=["id"]),
    "interviews": AshbyEndpointConfig(name="interviews", path="interview.list", primary_key=["id"]),
    "interview_schedules": AshbyEndpointConfig(
        name="interview_schedules", path="interviewSchedule.list", primary_key=["id"]
    ),
    "users": AshbyEndpointConfig(name="users", path="user.list", primary_key=["id"]),
    "departments": AshbyEndpointConfig(name="departments", path="department.list", primary_key=["id"]),
    "locations": AshbyEndpointConfig(name="locations", path="location.list", primary_key=["id"]),
    "sources": AshbyEndpointConfig(name="sources", path="source.list", primary_key=["id"]),
    "archive_reasons": AshbyEndpointConfig(name="archive_reasons", path="archiveReason.list", primary_key=["id"]),
    "candidate_tags": AshbyEndpointConfig(name="candidate_tags", path="candidateTag.list", primary_key=["id"]),
    "custom_fields": AshbyEndpointConfig(name="custom_fields", path="customField.list", primary_key=["id"]),
    "openings": AshbyEndpointConfig(name="openings", path="opening.list", primary_key=["id"]),
    "projects": AshbyEndpointConfig(name="projects", path="project.list", primary_key=["id"]),
}

ENDPOINTS = tuple(ASHBY_ENDPOINTS.keys())
