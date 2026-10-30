from dataclasses import dataclass
from typing import Any, Optional

PAGE_SIZE = 100  # Ashby's documented max (and default).


@dataclass(frozen=True)
class AshbyFanoutConfig:
    parent_path: str
    """Ashby list method walked to enumerate parents. Not necessarily a table we expose."""
    resolve_param: str
    """Request-body key on the child method that takes the parent's ``id``."""
    parent_id_field: Optional[str] = None
    """Field the parent's ``id`` is written onto, for children that don't already carry it."""


@dataclass(frozen=True)
class AshbyEndpointConfig:
    name: str
    """Table name we expose to the user (snake_case)."""
    path: str
    """Ashby RPC method, e.g. ``candidate.list`` (called as POST ``/<path>``)."""
    primary_key: list[str]
    partition_key: Optional[str] = None
    """A STABLE creation-time field to partition on. ``None`` disables partitioning.

    Only set where the object is documented to carry a top-level creation timestamp that Ashby
    never rewrites — never a mutable field like ``updatedAt`` (partitions would rewrite on
    every sync).
    """
    page_size: Optional[int] = PAGE_SIZE
    """``None`` for methods that accept no ``limit`` — Ashby rejects unknown request-body keys."""
    nested_field: Optional[str] = None
    """Rows come from this array on each item of ``path``, instead of from the items themselves."""
    fanout: Optional[AshbyFanoutConfig] = None
    """Set when ``path`` must be called once per parent row rather than listed directly."""
    variant_param: Optional[str] = None
    """Required request-body key that ``path`` is listed once per value of ``variant_values`` for."""
    variant_values: tuple[str, ...] = ()

    @property
    def probe_path(self) -> str:
        """Path to probe when validating access to this table.

        A fan-out child can't be called without a parent id, so we probe the parent listing the
        sync starts from; both sit behind the same Ashby permission.
        """
        return self.fanout.parent_path if self.fanout else self.path

    @property
    def probe_body(self) -> dict[str, Any]:
        """Smallest valid request body for ``probe_path``."""
        if self.fanout:
            return {"limit": 1}
        body: dict[str, Any] = {} if self.page_size is None else {"limit": 1}
        if self.variant_param and self.variant_values:
            body[self.variant_param] = self.variant_values[0]
        return body


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
    "referrals": AshbyEndpointConfig(
        name="referrals", path="referral.list", primary_key=["id"], partition_key="createdAt"
    ),
    "sequences": AshbyEndpointConfig(
        name="sequences", path="sequence.list", primary_key=["id"], partition_key="createdAt"
    ),
    "application_feedback": AshbyEndpointConfig(
        name="application_feedback",
        path="applicationFeedback.list",
        primary_key=["id"],
        partition_key="submittedAt",
    ),
    "application_history": AshbyEndpointConfig(
        name="application_history",
        path="application.listHistory",
        primary_key=["applicationId", "id"],
        # enteredStageAt is editable through application.updateHistory, so it can't partition.
        fanout=AshbyFanoutConfig(
            parent_path="application.list", resolve_param="applicationId", parent_id_field="applicationId"
        ),
    ),
    "interview_stages": AshbyEndpointConfig(
        name="interview_stages",
        path="interviewStage.list",
        primary_key=["interviewPlanId", "id"],
        page_size=None,
        fanout=AshbyFanoutConfig(parent_path="interviewPlan.list", resolve_param="interviewPlanId"),
    ),
    "interview_events": AshbyEndpointConfig(
        name="interview_events",
        path="interviewSchedule.list",
        primary_key=["id"],
        partition_key="createdAt",
        # interviewSchedule.list already returns every event in full, so read them from there
        # instead of calling interviewEvent.list once per schedule.
        nested_field="interviewEvents",
    ),
    "interview_stage_groups": AshbyEndpointConfig(
        name="interview_stage_groups", path="interviewStageGroup.list", primary_key=["id"], page_size=None
    ),
    "application_hiring_team_roles": AshbyEndpointConfig(
        name="application_hiring_team_roles",
        path="applicationHiringTeamRole.list",
        primary_key=["id"],
        page_size=None,
    ),
    "survey_submissions": AshbyEndpointConfig(
        name="survey_submissions",
        path="surveySubmission.list",
        primary_key=["id"],
        partition_key="submittedAt",
        # surveyType is required, and these are the only types the method lists.
        variant_param="surveyType",
        variant_values=("CandidateExperience", "Questionnaire", "HiringManagerExperience"),
    ),
    "candidate_notes": AshbyEndpointConfig(
        name="candidate_notes",
        path="candidate.listNotes",
        primary_key=["candidateId", "id"],
        partition_key="createdAt",
        fanout=AshbyFanoutConfig(
            parent_path="candidate.list", resolve_param="candidateId", parent_id_field="candidateId"
        ),
    ),
}

ENDPOINTS = tuple(ASHBY_ENDPOINTS.keys())
