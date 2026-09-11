"""Unit tests for logic/debt_digest.py — the daily visual review debt reminder."""

from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.utils import timezone

from posthog_owners.schema import TeamEntry

from posthog.models.team.team import Team
from posthog.team_notifications.slack import MAX_SECTION_CHARS, SlackChannel, SlackPostRefused

from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM, PathOwnership
from products.visual_review.backend.facade.contracts import (
    FLAKINESS_EXPIRY_SOON_DAYS,
    CreateRunInput,
    SnapshotManifestItem,
)
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.logic import artifact_store, debt_digest, quarantine, repos, runs, story_index
from products.visual_review.backend.models import ToleratedHash
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_PRODUCT_PATH = "products/visual_review/"
_SOURCE_PATH = "frontend/src/scenes/Button.stories.tsx"
_STORY_ID = "scenes-app-button--primary"
_IDENTIFIER = f"{_STORY_ID}--light"
_ABSENT_IDENTIFIER = "scenes-app-gone--primary--light"
_GITHUB_RUN_ID = "98765"
_INDEX = story_index.StoryIndex(path_by_story_id={_STORY_ID: _SOURCE_PATH})

_PLACED = debt_digest.Attribution(kind=debt_digest.AttributionKind.PLACED, source_path=_SOURCE_PATH)
_STORY_ABSENT = debt_digest.Attribution(kind=debt_digest.AttributionKind.STORY_ABSENT)
_UNAVAILABLE = debt_digest.Attribution(
    kind=debt_digest.AttributionKind.UNAVAILABLE,
    detail=f"the Storybook build artifact for run {_GITHUB_RUN_ID} was not read",
)


def _ownership(team_by_path: dict[str, str], registry: dict[str, TeamEntry] | None = None) -> PathOwnership:
    return PathOwnership(team_by_path=team_by_path, registry=registry or {}, resolved=True)


def _item(
    attribution: debt_digest.Attribution, identifier: str = _IDENTIFIER, line: str = "a line"
) -> debt_digest.DebtItem:
    return debt_digest.DebtItem(identifier=identifier, run_type="storybook", attribution=attribution, line=line)


def _with_index(index: story_index.StoryIndex | None):
    return patch("products.visual_review.backend.logic.story_index.fetch_story_index", return_value=index)


def _digest(team_slug: str = "team-devex") -> debt_digest.TeamDigest:
    return debt_digest.TeamDigest(team_slug=team_slug, expiring_quarantines=[_item(_PLACED)], variant_pileups=[])


def _triage_digest() -> debt_digest.TeamDigest:
    return debt_digest.TeamDigest(
        team_slug="team-devex",
        expiring_quarantines=[],
        variant_pileups=[],
        triage=[
            debt_digest.TriageGroup(kind=debt_digest.AttributionKind.PLACED, items=[_item(_PLACED)]),
            debt_digest.TriageGroup(kind=debt_digest.AttributionKind.UNAVAILABLE, items=[_item(_UNAVAILABLE)]),
        ],
    )


class TestRendering:
    @pytest.mark.parametrize("run_type", ["storybook", "<!channel>"])
    def test_escapes_slack_control_characters_in_user_text(self, run_type: str) -> None:
        # A reason, an identifier and a run type are all contributor input; any of them could
        # otherwise smuggle a <!channel> mention into every owning team's channel.
        entry = MagicMock(
            identifier="Button<!channel>",
            run_type=run_type,
            reason="flaky & <!here>",
            expires_at=timezone.now() + timedelta(days=3),
            created_by_id=None,
        )
        repo = MagicMock(id="00000000-0000-0000-0000-000000000001", team_id=7, repo_full_name="PostHog/posthog")

        line = debt_digest._quarantine_line(repo, entry, {}, timezone.now())
        pileup = debt_digest._pileup_line(repo, run_type, "Button", 4)

        assert "<!channel>" not in line
        assert "<!channel>" not in pileup
        assert "<!here>" not in line
        assert "&lt;!channel&gt;" in line
        assert "flaky &amp; &lt;!here&gt;" in line

    def test_links_to_the_snapshot_page_with_encoded_segments(self) -> None:
        repo = MagicMock(id="abc", team_id=7, repo_full_name="PostHog/posthog")

        line = debt_digest._pileup_line(repo, "storybook", "scenes/Button--dark", 4)

        assert line.startswith("4 accepted variants of the current baseline · scenes/Button--dark (storybook)")
        assert line.endswith("/project/7/visual_review/repos/abc/storybook/snapshots/scenes%2FButton--dark")

    @pytest.mark.parametrize(
        "identifier,reason,links_to_the_snapshot",
        [
            ("b" * 512, "non-deterministic", True),
            # Each of these percent-encodes to nine characters, so the URL alone outgrows a block.
            ("界" * 400, "non-deterministic", False),
            ("Button--light", "because " * 100, True),
        ],
    )
    def test_one_oversized_item_still_fits_a_slack_block(
        self, identifier: str, reason: str, links_to_the_snapshot: bool
    ) -> None:
        repo = MagicMock(id="abc", team_id=7, repo_full_name="PostHog/posthog")
        entry = MagicMock(
            identifier=identifier,
            run_type="storybook",
            reason=reason,
            expires_at=timezone.now() + timedelta(days=3),
            created_by_id=None,
        )

        line = debt_digest._quarantine_line(repo, entry, {}, timezone.now())
        texts = debt_digest.thread_texts(
            debt_digest.TeamDigest(
                team_slug="team-devex",
                expiring_quarantines=[_item(_PLACED, identifier=identifier, line=line)] * 2,
                variant_pileups=[],
            )
        )

        assert len(line) <= debt_digest._MAX_LINE_CHARS
        assert settings.SITE_URL in line
        assert ("/snapshots/" in line) == links_to_the_snapshot
        assert all(len(text) <= MAX_SECTION_CHARS for text in texts)

    def test_splits_the_thread_when_one_group_runs_long(self) -> None:
        long_item = _item(_PLACED, line="x" * 2000)
        digest = debt_digest.TeamDigest(
            team_slug="team-devex", expiring_quarantines=[long_item, long_item], variant_pileups=[]
        )

        texts = debt_digest.thread_texts(digest)

        assert len(texts) > 1
        assert all(len(text) <= MAX_SECTION_CHARS for text in texts)
        assert texts[-1].endswith(debt_digest._FOOTER)

    def test_the_lead_holds_triage_apart_from_what_the_team_owns(self) -> None:
        repo = MagicMock(id="abc", team_id=7, repo_full_name="PostHog/posthog")

        lead = debt_digest.lead_text(_triage_digest(), repo)

        assert "nothing this team owns today" in lead
        assert "2 in triage that nobody owns yet" in lead
        # An artifact that could not be read must never read as "nobody owns this".
        assert f"the Storybook build artifact for run {_GITHUB_RUN_ID} was not read" in lead
        assert "tries again tomorrow" in lead

    def test_the_thread_groups_triage_under_one_header_per_reason(self) -> None:
        thread = "\n".join(debt_digest.thread_texts(_triage_digest()))

        assert debt_digest._TRIAGE_HEADERS[debt_digest.AttributionKind.PLACED] in thread
        assert debt_digest._TRIAGE_HEADERS[debt_digest.AttributionKind.UNAVAILABLE] in thread
        # The path stays on the line, because it is what an owners entry is written for.
        assert f"a line · {_SOURCE_PATH}" in thread
        assert f"a line · the Storybook build artifact for run {_GITHUB_RUN_ID} was not read" in thread


class TestSplitByTeam:
    def test_routes_a_placed_item_to_the_team_that_owns_its_file(self) -> None:
        placed = _item(_PLACED, line="placed")
        absent = _item(_STORY_ABSENT, identifier=_ABSENT_IDENTIFIER, line="absent")
        debt = debt_digest.RepoDebt(expiring_quarantines=[placed], variant_pileups=[absent])

        digests = debt_digest.split_by_team(
            debt, _ownership({_SOURCE_PATH: "team-product-analytics", _PRODUCT_PATH: "team-devex"})
        )

        by_slug = {d.team_slug: d for d in digests}
        assert set(by_slug) == {"team-product-analytics", "team-devex"}
        assert by_slug["team-product-analytics"].expiring_quarantines == [placed]
        # The maintainers hold the other item without it counting as debt of their own.
        assert by_slug["team-devex"].variant_pileups == []
        assert by_slug["team-devex"].triage == [
            debt_digest.TriageGroup(kind=debt_digest.AttributionKind.STORY_ABSENT, items=[absent])
        ]

    @pytest.mark.parametrize("attribution", [_PLACED, _STORY_ABSENT, _UNAVAILABLE])
    def test_keeps_the_three_unowned_outcomes_apart(self, attribution: debt_digest.Attribution) -> None:
        item = _item(attribution)
        debt = debt_digest.RepoDebt(expiring_quarantines=[item], variant_pileups=[])

        digests = debt_digest.split_by_team(debt, _ownership({_PRODUCT_PATH: "team-devex"}))

        assert [d.team_slug for d in digests] == ["team-devex"]
        assert digests[0].expiring_quarantines == []
        assert digests[0].triage == [debt_digest.TriageGroup(kind=attribution.kind, items=[item])]

    def test_drops_an_item_nobody_owns(self) -> None:
        debt = debt_digest.RepoDebt(expiring_quarantines=[_item(_STORY_ABSENT)], variant_pileups=[])

        assert debt_digest.split_by_team(debt, _ownership({})) == []


class TestRouting:
    _CHANNELS = {
        "team-devex": SlackChannel(channel_id="C1", shared=False),
        "team-shared": SlackChannel(channel_id="C2", shared=True),
    }

    def test_a_team_that_opted_out_is_skipped(self) -> None:
        registry = {"team-devex": TeamEntry(notifications={"visual_review": False})}

        assert debt_digest.resolve_channel(_digest(), registry, self._CHANNELS) is None

    def test_a_shared_channel_is_refused(self) -> None:
        # A name match onto a shared channel would send an internal reminder out of the workspace.
        assert debt_digest.resolve_channel(_digest("team-shared"), {}, self._CHANNELS) is None

    @pytest.mark.parametrize("mode", ["preveiw", "shadow", ""])
    def test_an_unknown_mode_evaluates_nothing_and_posts_nothing(self, mode: str) -> None:
        with (
            patch("products.visual_review.backend.logic.debt_digest.collect_debt") as collect,
            patch("products.visual_review.backend.logic.debt_digest.post_with_join") as post,
        ):
            assert debt_digest.send_debt_digest(MagicMock(), mode=mode) == []

        assert collect.call_count == 0
        assert post.call_count == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestReposInScope:
    def test_every_repo_is_in_scope_whatever_team_owns_it(self, team) -> None:
        mine = repos.create_repo(team_id=team.id, repo_external_id=77781, repo_full_name="org/mine")
        other_team = Team.objects.create(organization=team.organization, name="other")
        theirs = repos.create_repo(team_id=other_team.id, repo_external_id=77782, repo_full_name="org/theirs")

        assert {(repo.team_id, repo.id) for repo in debt_digest.repos_in_scope()} == {
            (mine.team_id, mine.id),
            (theirs.team_id, theirs.id),
        }


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestCollectAndSend:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=77771, repo_full_name="org/test-debt")

    def _completed_run(self, repo, mocker, identifiers=(_IDENTIFIER,)):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="new_hash", storage_path="p/new_hash")
        baselines = dict.fromkeys(identifiers, "old_hash")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                metadata={"github_run_id": _GITHUB_RUN_ID},
                snapshots=[
                    SnapshotManifestItem(identifier=identifier, content_hash="new_hash") for identifier in identifiers
                ],
                baseline_hashes=baselines,
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=(baselines, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)
        return run

    def _pile_up(self, repo, identifier=_IDENTIFIER, count=3):
        for index in range(count):
            ToleratedHash.objects.create(
                repo=repo,
                team_id=repo.team_id,
                identifier=identifier,
                baseline_hash="old_hash",
                alternate_hash=f"variant_{index}",
                reason="human",
            )

    def test_collects_both_conditions_and_names_the_story_file(self, repo, team, user, mocker):
        self._completed_run(repo, mocker)
        self._pile_up(repo)
        now = timezone.now()
        quarantine.quarantine_identifier(
            repo_id=repo.id,
            identifier=_ABSENT_IDENTIFIER,
            run_type=RunType.STORYBOOK,
            reason="non-deterministic",
            user_id=user.id,
            team_id=team.id,
            expires_at=now + timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS - 1),
        )

        with _with_index(_INDEX):
            debt = debt_digest.collect_debt(repo, now)

        assert [(item.identifier, item.attribution) for item in debt.variant_pileups] == [(_IDENTIFIER, _PLACED)]
        # A story the index does not hold is absent, which is not the same as nobody owning it.
        assert [(item.identifier, item.attribution) for item in debt.expiring_quarantines] == [
            (_ABSENT_IDENTIFIER, _STORY_ABSENT)
        ]
        assert "3 accepted variants of the current baseline" in debt.variant_pileups[0].line

    def test_an_unreadable_artifact_leaves_the_items_unattributed(self, repo, mocker):
        self._completed_run(repo, mocker)
        self._pile_up(repo)

        with _with_index(None):
            debt = debt_digest.collect_debt(repo, timezone.now())

        assert [item.attribution for item in debt.variant_pileups] == [_UNAVAILABLE]

    @pytest.mark.parametrize(
        "expires_in,expected_expiring",
        [
            (timedelta(days=1), [_IDENTIFIER]),
            (timedelta(days=60), []),
            (None, []),
        ],
    )
    def test_a_quarantined_identity_is_not_also_reported_for_its_variants(
        self, repo, team, user, mocker, expires_in, expected_expiring
    ):
        self._completed_run(repo, mocker)
        self._pile_up(repo)
        now = timezone.now()
        quarantine.quarantine_identifier(
            repo_id=repo.id,
            identifier=_IDENTIFIER,
            run_type=RunType.STORYBOOK,
            reason="non-deterministic",
            user_id=user.id,
            team_id=team.id,
            expires_at=now + expires_in if expires_in is not None else None,
        )

        with _with_index(_INDEX):
            debt = debt_digest.collect_debt(repo, now)

        assert [item.identifier for item in debt.expiring_quarantines] == expected_expiring
        assert debt.variant_pileups == []

    def test_preview_renders_every_team_and_posts_nothing(self, repo, mocker):
        self._completed_run(repo, mocker)
        self._pile_up(repo)
        with (
            _with_index(_INDEX),
            patch(
                "products.visual_review.backend.logic.debt_digest.resolve_path_owners",
                return_value=_ownership({_SOURCE_PATH: "team-devex", _PRODUCT_PATH: "team-devex"}),
            ),
            patch("products.visual_review.backend.logic.debt_digest.fetch_channel_map") as channel_map,
            patch("products.visual_review.backend.logic.debt_digest.post_with_join") as post,
        ):
            rendered = debt_digest.send_debt_digest(repo, mode=debt_digest.MODE_PREVIEW)

        assert post.call_count == 0
        assert channel_map.call_count == 0
        assert len(rendered) == 1
        assert rendered[0].startswith("Visual review debt for team-devex in org/test-debt: ")

    def test_an_unreadable_owners_file_sends_nothing(self, repo, mocker):
        self._completed_run(repo, mocker)
        self._pile_up(repo)
        # Every path reads as unowned when the owners files could not be read, which would
        # otherwise drop the whole repo's debt as nobody's.
        blind = PathOwnership(
            team_by_path={_SOURCE_PATH: UNOWNED_TEAM, _PRODUCT_PATH: UNOWNED_TEAM}, registry={}, resolved=False
        )
        with (
            _with_index(_INDEX),
            patch("products.visual_review.backend.logic.debt_digest.resolve_path_owners", return_value=blind),
            patch("products.visual_review.backend.logic.debt_digest.post_with_join") as post,
        ):
            assert debt_digest.send_debt_digest(repo, mode=debt_digest.MODE_LIVE) == []

        assert post.call_count == 0

    def test_one_team_failing_does_not_stop_the_next(self, repo, mocker):
        self._completed_run(repo, mocker, (_IDENTIFIER, _ABSENT_IDENTIFIER))
        self._pile_up(repo)
        self._pile_up(repo, identifier=_ABSENT_IDENTIFIER)
        with (
            _with_index(_INDEX),
            patch(
                "products.visual_review.backend.logic.debt_digest.resolve_path_owners",
                return_value=_ownership({_SOURCE_PATH: "team-one", _PRODUCT_PATH: "team-two"}),
            ),
            patch("products.visual_review.backend.logic.debt_digest.Integration") as integration,
            patch("products.visual_review.backend.logic.debt_digest.SlackIntegration"),
            patch(
                "products.visual_review.backend.logic.debt_digest.fetch_channel_map",
                return_value={
                    "team-one": SlackChannel(channel_id="C1", shared=False),
                    "team-two": SlackChannel(channel_id="C2", shared=False),
                },
            ),
            patch(
                "products.visual_review.backend.logic.debt_digest.post_with_join",
                side_effect=[SlackPostRefused("no"), "1700000000.1"],
            ) as post,
            patch("products.visual_review.backend.logic.debt_digest.post_message") as thread_post,
        ):
            integration.objects.filter.return_value.first.return_value = MagicMock()
            debt_digest.send_debt_digest(repo, mode=debt_digest.MODE_LIVE)

        assert post.call_count == 2
        assert thread_post.call_count == 1
