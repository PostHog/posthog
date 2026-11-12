import math
from datetime import timedelta
from typing import Literal
from uuid import UUID

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import User
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.testing import create_role
from products.error_tracking.backend.logic.auto_assignment.evidence import (
    IssueEmbedding,
    IssueEvidence,
    SimilarAssignedIssue,
    SimilarIssueLookup,
)
from products.error_tracking.backend.logic.auto_assignment.gate import AutoAssignmentConfig, HistoryConfig
from products.error_tracking.backend.logic.auto_assignment.history import HistoryVote
from products.error_tracking.backend.logic.issue_changes import AssigneeRef
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)

ALICE = AssigneeRef(type="user", id="1")
BOB = AssigneeRef(type="user", id="2")
CONFIG = AutoAssignmentConfig(history=HistoryConfig(top_k=3, max_distance=0.2, min_confidence=0.66))
MODEL = "text-embedding-3-small-1536"


def _evidence(*matches: tuple[AssigneeRef, float]) -> MagicMock:
    evidence = MagicMock()
    evidence.similar_assigned_issues = SimilarIssueLookup(
        issues=tuple(
            SimilarAssignedIssue(issue_id=f"issue-{i}", assignee=assignee, distance=distance)
            for i, (assignee, distance) in enumerate(matches)
        ),
    )
    return evidence


class TestHistoryVote(SimpleTestCase):
    @parameterized.expand(
        [
            ("agree", [(ALICE, 0.05), (ALICE, 0.1), (BOB, 0.12)], ALICE, 2 / 3, ("issue-0", "issue-1")),
            (
                "disagree_nearest_wins_tie",
                [(BOB, 0.05), (ALICE, 0.1), (AssigneeRef(type="role", id="r"), 0.12)],
                BOB,
                1 / 3,
                ("issue-0",),
            ),
            ("far_matches_do_not_vote", [(ALICE, 0.05), (BOB, 0.3), (BOB, 0.4)], ALICE, 1 / 3, ("issue-0",)),
            (
                "only_top_k_vote",
                [(ALICE, 0.01), (ALICE, 0.02), (BOB, 0.03), (BOB, 0.04), (BOB, 0.05)],
                ALICE,
                2 / 3,
                ("issue-0", "issue-1"),
            ),
        ]
    )
    def test_vote(
        self,
        _name: str,
        matches: list[tuple[AssigneeRef, float]],
        assignee: AssigneeRef,
        confidence: float,
        similar_issue_ids: tuple[str, ...],
    ) -> None:
        candidate = HistoryVote().propose(_evidence(*matches), CONFIG)

        assert candidate is not None
        assert candidate.assignee == assignee
        assert candidate.confidence == confidence
        assert candidate.evidence.similar_issue_ids == similar_issue_ids

    @parameterized.expand(
        [
            ("no_history", ()),
            ("all_below_similarity_threshold", ((ALICE, 0.3), (ALICE, 0.4))),
        ]
    )
    def test_no_candidate(self, _name: str, matches: tuple[tuple[AssigneeRef, float], ...]) -> None:
        assert HistoryVote().propose(_evidence(*matches), CONFIG) is None

    def test_no_embedding_means_no_candidate(self) -> None:
        evidence = MagicMock(similar_assigned_issues=None)

        assert HistoryVote().propose(evidence, CONFIG) is None


def _vector(*values: float) -> list[float]:
    return [*values, *([0.0] * (1536 - len(values)))]


class TestSimilarAssignedIssues(ClickhouseTestMixin, BaseTest):
    def _issue(
        self,
        fingerprint: str,
        vector: list[float],
        *,
        assignee: Literal["user", "neither"] | User | UUID | None = "user",
    ) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name=fingerprint)
        self._fingerprint(issue, fingerprint, vector)
        if assignee == "user":
            ErrorTrackingIssueAssignment.objects.create(issue=issue, team=self.team, user=self.user)
        elif assignee == "neither":
            ErrorTrackingIssueAssignment.objects.create(issue=issue, team=self.team)
        elif isinstance(assignee, User):
            ErrorTrackingIssueAssignment.objects.create(issue=issue, team=self.team, user=assignee)
        elif assignee is not None:
            ErrorTrackingIssueAssignment.objects.create(issue=issue, team=self.team, role_id=assignee)
        return issue

    def _fingerprint(self, issue: ErrorTrackingIssue, fingerprint: str, vector: list[float]) -> None:
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        now = timezone.now()
        sync_execute(
            """
            INSERT INTO distributed_posthog_document_embeddings_text_embedding_3_small_1536 (
                team_id, product, document_type, rendering, document_id, timestamp, inserted_at,
                content, metadata, embedding, _timestamp, _offset, _partition
            ) VALUES
            """,
            [(self.team.id, "error_tracking", "fingerprint", "r", fingerprint, now, now, "", "{}", vector, now, 0, 0)],
            flush=True,
            team_id=self.team.pk,
        )

    def test_returns_assigned_past_issues_nearest_first(self) -> None:
        near = self._issue("near", _vector(1.0, 0.1))
        self._fingerprint(near, "near-2", _vector(1.0, 0.05))
        far = self._issue("far", _vector(1.0, 1.0))
        role_id = create_role(organization_id=self.organization.id, name="Backend")
        by_role = self._issue("by-role", _vector(1.0, 2.0), assignee=role_id)
        self._issue("unassigned", _vector(1.0), assignee=None)
        self._issue("no-user-or-role", _vector(1.0), assignee="neither")
        former_member = self._create_user("former@example.com")
        OrganizationMembership.objects.filter(user=former_member, organization=self.organization).delete()
        self._issue("former-member", _vector(1.0), assignee=former_member)
        late = self._issue("assigned-later", _vector(1.0))
        seen_later = self._issue("seen-later", _vector(1.0))
        target = self._issue("target", _vector(1.0))
        created_at = timezone.now() + timedelta(minutes=1)
        ErrorTrackingIssueAssignment.objects.filter(issue=late).update(created_at=created_at + timedelta(hours=1))
        ErrorTrackingIssueFingerprintV2.objects.filter(issue=seen_later).update(
            first_seen=created_at + timedelta(hours=1)
        )

        evidence = IssueEvidence(
            team=self.team,
            issue_id=str(target.id),
            created_at=created_at,
            embedding=IssueEmbedding(model_name=MODEL, rendering="r", vector=tuple(_vector(1.0))),
        )
        lookup = evidence.similar_assigned_issues

        assert lookup is not None
        assert [issue.issue_id for issue in lookup.issues] == [str(near.id), str(far.id), str(by_role.id)]
        assert lookup.issues[0].distance == pytest.approx(1 - 1 / math.sqrt(1 + 0.05**2), abs=1e-5)
        assert lookup.issues[0].assignee == AssigneeRef(type="user", id=str(self.user.id))
        assert lookup.issues[2].assignee == AssigneeRef(type="role", id=str(role_id))
