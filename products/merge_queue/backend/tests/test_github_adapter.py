import pytest

from products.merge_queue.backend.github import adapter
from products.merge_queue.backend.github.adapter import PullRequestSignal
from products.merge_queue.backend.github.bot_accounts import BotRegistry, Review, has_valid_approval
from products.merge_queue.backend.models import Enrollment, EnrollmentState


def _signal(*, author="bob", reviews=None, checks=None, required=("ci",), files=(), labels=()) -> PullRequestSignal:
    return PullRequestSignal(
        repo="PostHog/posthog",
        number=42,
        head_sha="a" * 40,
        author_login=author,
        reviews=list(reviews if reviews is not None else [Review("alice", "approved")]),
        checks=dict(checks if checks is not None else {"ci": "success"}),
        required_checks=list(required),
        changed_files=list(files),
        labels=list(labels),
    )


class TestToFacts:
    def test_approved_and_green(self):
        facts = adapter.to_facts(_signal())
        assert facts.approved is True
        assert facts.checks_green is True

    def test_self_approval_does_not_count(self):
        facts = adapter.to_facts(_signal(author="bot", reviews=[Review("bot", "approved")]))
        assert facts.approved is False

    def test_empty_required_checks_is_not_green(self):
        assert adapter.to_facts(_signal(required=())).checks_green is False

    def test_failing_required_check_is_not_green(self):
        assert adapter.to_facts(_signal(checks={"ci": "failure"})).checks_green is False


@pytest.mark.django_db
class TestIngest:
    def test_eligible_pr_enrolls(self, engine, partition_factory):
        partition_factory()
        status = adapter.ingest(_signal())
        assert status is not None
        assert status.state == EnrollmentState.ACTIVE
        assert Enrollment.objects.filter(state="active").count() == 1

    @pytest.mark.parametrize(
        "signal_kwargs",
        [
            {"reviews": []},  # not approved
            {"checks": {"ci": "failure"}},  # checks red
            {"author": "bot", "reviews": [Review("bot", "approved")]},  # self-approval only
        ],
    )
    def test_ineligible_pr_does_not_enroll(self, engine, partition_factory, signal_kwargs):
        partition_factory()
        assert adapter.ingest(_signal(**signal_kwargs)) is None
        assert not Enrollment.objects.filter(state="active").exists()

    def test_ingest_is_idempotent(self, engine, partition_factory):
        partition_factory()
        adapter.ingest(_signal())
        again = adapter.ingest(_signal())
        assert again is not None
        assert Enrollment.objects.filter(state="active").count() == 1


class TestBotRegistry:
    def test_actor_kind_from_bot_membership(self):
        registry = BotRegistry({"posthog-bot"})
        assert registry.actor_for("posthog-bot").kind.value == "agent"
        assert registry.actor_for("alice").kind.value == "human"

    def test_has_valid_approval_ignores_non_approvals(self):
        reviews = [Review("alice", "commented"), Review("carol", "changes_requested")]
        assert has_valid_approval(reviews, pr_author_login="bob") is False
