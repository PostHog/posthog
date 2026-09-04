from datetime import UTC, datetime
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.reaper_hog.backend.facade.enums import ClusterRank, ClusterStatus, Confidence, RootKind, ScoutName
from products.reaper_hog.backend.logic.artefacts import Hit, Verdict, VerdictRecord
from products.reaper_hog.backend.logic.converge import converge
from products.reaper_hog.backend.logic.inventory import record_scan, upsert_inventory
from products.reaper_hog.backend.logic.skill import PinnedSkill
from products.reaper_hog.backend.logic.verification import (
    ClusterView,
    VerifyRequest,
    build_verification_prompt,
    run_verification,
)
from products.reaper_hog.backend.models import ReaperArtefact, ReaperCluster
from products.reaper_hog.backend.tests.conftest import PRODUCT_DATABASES

_MODULE = "products.reaper_hog.backend.logic.verification"
NOW = datetime(2026, 8, 30, tzinfo=UTC)


def _verdict(is_dead: bool, confidence: Confidence) -> Verdict:
    return Verdict(is_dead=is_dead, confidence=confidence, deletion_plan="plan", argumentation="- **Checked:** x")


def _hit(root: str, *, decisive: bool = True) -> Hit:
    return Hit(
        scout=ScoutName.FLAGS, root_kind=RootKind.FLAG, root=root, files=["a.py"], decisive=decisive, summary="s"
    )


def _seed(team, *roots: str, blocked: str | None = None):
    inventory = upsert_inventory(team_id=team.id, repository="o/r", scope="flags")
    record_scan(inventory, converge(_hit(root) for root in roots), head_sha="abc", now=NOW)
    if blocked:
        ReaperCluster.objects.filter(inventory=inventory, root=blocked).update(blocked_reason="oversize")
    return inventory


def _request(team, user) -> VerifyRequest:
    return VerifyRequest(team_id=team.id, user_id=user.id, repository="o/r", scope="flags")


def _run(request: VerifyRequest, *, start: AsyncMock, cont: AsyncMock, end: AsyncMock):
    with (
        patch(f"{_MODULE}.start_session", start),
        patch(f"{_MODULE}.continue_session", cont),
        patch(f"{_MODULE}.end_session", end),
        patch(
            f"{_MODULE}.sync_verification_skill",
            return_value=PinnedSkill(name="reaper-hog-verification-criteria", version=1),
        ),
    ):
        return run_verification(request)


@pytest.mark.django_db(transaction=True, databases=PRODUCT_DATABASES)
class TestVerifyInventory:
    def test_verdicts_drive_status_and_skip_blocked_clusters(self, team, user):
        inventory = _seed(team, "a", "b", "c", blocked="c")
        session = MagicMock()
        start = AsyncMock(return_value=(session, _verdict(True, Confidence.HIGH)))
        cont = AsyncMock(return_value=_verdict(False, Confidence.HIGH))
        end = AsyncMock()

        result = _run(_request(team, user), start=start, cont=cont, end=end)

        statuses = {c.root: c.status for c in ReaperCluster.objects.filter(inventory=inventory)}
        assert statuses == {"a": ClusterStatus.DEAD, "b": ClusterStatus.ALIVE, "c": ClusterStatus.CANDIDATE}
        assert (result.verified, result.dead, result.alive, result.failed) == (2, 1, 1, 0)
        verdicts = ReaperArtefact.objects.filter(inventory=inventory, type="verdict")
        assert {VerdictRecord.model_validate_json(v.content).head_sha for v in verdicts} == {"abc"}
        assert ReaperCluster.objects.get(inventory=inventory, root="a").verified_sha == "abc"
        end.assert_awaited_once_with(session, status="completed", error=None)

    def test_failed_turn_keeps_the_candidate_and_restarts_the_session(self, team, user):
        inventory = _seed(team, "a", "b", "d")
        first, second = MagicMock(), MagicMock()
        start = AsyncMock(
            side_effect=[(first, _verdict(True, Confidence.HIGH)), (second, _verdict(True, Confidence.LOW))]
        )
        cont = AsyncMock(side_effect=RuntimeError("sandbox timeout"))
        end = AsyncMock()

        result = _run(_request(team, user), start=start, cont=cont, end=end)

        statuses = {c.root: c.status for c in ReaperCluster.objects.filter(inventory=inventory)}
        assert statuses == {"a": ClusterStatus.DEAD, "b": ClusterStatus.CANDIDATE, "d": ClusterStatus.UNDECIDED}
        assert (result.verified, result.undecided, result.failed) == (2, 1, 1)
        assert end.await_args_list[0].args == (first,)
        assert end.await_args_list[0].kwargs["status"] == "failed"
        assert end.await_args_list[1] == ((second,), {"status": "completed", "error": None})


def test_prompt_pins_the_skill_and_carries_scout_evidence() -> None:
    view = ClusterView(
        id=uuid4(),
        hash="h",
        root_kind=RootKind.FLAG,
        root="hero-copy",
        rank=ClusterRank.STRONG,
        files=("a.py",),
        hits=(_hit("hero-copy"),),
    )

    prompt = build_verification_prompt(view, PinnedSkill(name="reaper-hog-verification-criteria", version=3))

    assert 'skill-get(skill_name="reaper-hog-verification-criteria", version=3)' in prompt
    assert '"root": "hero-copy"' in prompt
    assert '"summary": "s"' in prompt
    assert '"is_dead"' in prompt
