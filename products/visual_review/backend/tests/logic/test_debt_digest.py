"""Unit tests for logic/debt_digest.py — the weekly visual review debt reminder."""

from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.utils import timezone

from posthog_owners.schema import TeamEntry

from posthog.models.team.team import Team
from posthog.team_notifications.slack import (
    MAX_BLOCKS,
    MAX_SECTION_CHARS,
    MAX_TEXT_CHARS,
    SlackChannel,
    SlackPostRefused,
)

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
_OTHER_PATH = "frontend/src/scenes/Card.stories.tsx"
_OTHER_STORY_ID = "scenes-app-card--primary"
_OTHER_IDENTIFIER = f"{_OTHER_STORY_ID}--light"
_ABSENT_IDENTIFIER = "scenes-app-gone--primary--light"
_GITHUB_RUN_ID = "98765"
_INDEX = story_index.StoryIndex(path_by_story_id={_STORY_ID: _SOURCE_PATH})

# The renderers take the moment they render for, so a fixed Monday never ages against a real clock.
_MONDAY = datetime(2026, 9, 14, 7, 30, tzinfo=UTC)

_PLACED = debt_digest.Attribution(kind=debt_digest.AttributionKind.PLACED, source_path=_SOURCE_PATH)
_STORY_ABSENT = debt_digest.Attribution(kind=debt_digest.AttributionKind.STORY_ABSENT)
_UNAVAILABLE = debt_digest.Attribution(
    kind=debt_digest.AttributionKind.UNAVAILABLE,
    detail=f"the Storybook build artifact for run {_GITHUB_RUN_ID} was not read",
)


def _ownership(team_by_path: dict[str, str], registry: dict[str, TeamEntry] | None = None) -> PathOwnership:
    return PathOwnership(team_by_path=team_by_path, registry=registry or {}, resolved=True)


def _repo() -> MagicMock:
    return MagicMock(id="abc", team_id=7, repo_full_name="PostHog/posthog")


def _item(
    attribution: debt_digest.Attribution,
    identifier: str = _IDENTIFIER,
    line: str = "a line",
    facts: str = "*3* accepted variants of the current baseline",
) -> debt_digest.DebtItem:
    return debt_digest.DebtItem(
        identifier=identifier, run_type="storybook", attribution=attribution, line=line, facts=facts
    )


def _team_digest(expiring: int = 0, pileups: int = 0, team_slug: str = "team-devex") -> debt_digest.TeamDigest:
    return debt_digest.TeamDigest(
        team_slug=team_slug,
        expiring_quarantines=[_item(_PLACED)] * expiring,
        variant_pileups=[_item(_PLACED)] * pileups,
    )


def _maintainers_digest(*groups: debt_digest.TriageGroup) -> debt_digest.MaintainersDigest:
    return debt_digest.MaintainersDigest(team_slug="team-devex", groups=list(groups))


def _with_index(index: story_index.StoryIndex | None):
    return patch("products.visual_review.backend.logic.story_index.fetch_story_index", return_value=index)


def _section_texts(message: debt_digest.SlackMessage) -> list[str]:
    return [block["text"]["text"] for block in message.blocks if block["type"] == "section" and "text" in block]


def _buttons(message: debt_digest.SlackMessage) -> list[dict]:
    accessories = [block["accessory"] for block in message.blocks if "accessory" in block]
    rows = [element for block in message.blocks if block["type"] == "actions" for element in block["elements"]]
    return [*accessories, *rows]


def _all_buttons(messages: list[debt_digest.SlackMessage]) -> list[dict]:
    return [button for message in messages for button in _buttons(message)]


class TestLead:
    @pytest.mark.parametrize(
        "expiring,pileups,fields,mentions_lapse",
        [
            (1, 0, ["*1 quarantine* expires soon"], True),
            (0, 2, ["*2 snapshots* with piled-up variants"], False),
            (3, 1, ["*3 quarantines* expire soon", "*1 snapshot* with piled-up variants"], True),
        ],
    )
    def test_the_lead_names_the_team_and_counts_only_the_conditions_it_has(
        self, expiring: int, pileups: int, fields: list[str], mentions_lapse: bool
    ) -> None:
        message = debt_digest.lead_message(_repo(), _team_digest(expiring, pileups), _MONDAY)

        assert message.blocks[0]["type"] == "header"
        assert message.blocks[0]["text"]["text"] == "Visual review debt for team-devex"
        assert [field["text"] for field in message.blocks[2]["fields"]] == fields
        assert ("Quarantines that lapse" in message.blocks[3]["text"]["text"]) is mentions_lapse
        assert "week of Sep 14" in message.blocks[1]["elements"][0]["text"]

    def test_the_lead_links_to_the_two_pages_the_counts_come_from(self) -> None:
        message = debt_digest.lead_message(_repo(), _team_digest(pileups=1), _MONDAY)

        assert [(button["text"]["text"], button["url"]) for button in _buttons(message)] == [
            ("Open flakiness overview", f"{settings.SITE_URL}/project/7/visual_review/repos/abc/flakiness"),
            ("Open snapshots", f"{settings.SITE_URL}/project/7/visual_review/repos/abc/snapshots"),
        ]

    def test_the_fallback_text_says_what_the_blocks_say(self) -> None:
        message = debt_digest.lead_message(_repo(), _team_digest(expiring=1, pileups=2), _MONDAY)

        assert message.text == (
            "Visual review debt for team-devex in PostHog/posthog: 1 quarantine expires soon, "
            "2 snapshots with piled-up variants."
        )


class TestThreadReplies:
    @pytest.mark.parametrize(
        "expiring,pileups,headings",
        [
            (1, 0, ["*Quarantines expiring soon*"]),
            (0, 1, ["*Snapshots with piled-up variants*"]),
            (2, 2, ["*Quarantines expiring soon*", "*Snapshots with piled-up variants*"]),
        ],
    )
    def test_one_reply_per_condition_that_has_items(self, expiring: int, pileups: int, headings: list[str]) -> None:
        messages = debt_digest.thread_messages(_repo(), _team_digest(expiring, pileups), _MONDAY)

        assert [_section_texts(message)[0].split("\n")[0] for message in messages] == headings

    def test_every_item_carries_the_one_button_that_resolves_it(self) -> None:
        messages = debt_digest.thread_messages(_repo(), _team_digest(expiring=1, pileups=1), _MONDAY)

        buttons = _all_buttons(messages)
        assert [button["text"]["text"] for button in buttons] == ["Extend or fix", "Reset baseline"]
        assert all(
            button["url"] == f"{settings.SITE_URL}/project/7/visual_review/repos/abc/storybook/snapshots/{_IDENTIFIER}"
            for button in buttons
        )

    def test_a_button_url_too_long_for_slack_points_at_the_repo_list(self) -> None:
        # Each of these percent-encodes to nine characters, so the URL alone outgrows the button.
        digest = debt_digest.TeamDigest(
            team_slug="team-devex", expiring_quarantines=[], variant_pileups=[_item(_PLACED, identifier="界" * 400)]
        )

        messages = debt_digest.thread_messages(_repo(), digest, _MONDAY)

        assert _all_buttons(messages)[0]["url"] == f"{settings.SITE_URL}/project/7/visual_review/repos/abc/snapshots"

    def test_the_last_reply_says_when_the_next_digest_comes(self) -> None:
        messages = debt_digest.thread_messages(_repo(), _team_digest(expiring=1, pileups=1), _MONDAY)

        assert messages[0].blocks[-1]["type"] == "section"
        assert messages[-1].blocks[-2]["type"] == "divider"
        assert messages[-1].blocks[-1]["elements"][0]["text"] == "Next digest Monday, Sep 21."

    @pytest.mark.parametrize(
        "browser_suffix,dark_facts,titles,urls",
        [
            (
                "",
                "Expires *Wednesday*",
                [f"*{_STORY_ID}* storybook · light and dark"],
                [f"{settings.SITE_URL}/project/7/visual_review/repos/abc/flakiness#preset=quarantined&q={_STORY_ID}"],
            ),
            # A webkit identifier puts the theme before the browser suffix, so the search has to
            # drop both to match the two variants.
            (
                "--webkit",
                "Expires *Wednesday*",
                [f"*{_STORY_ID}--webkit* storybook · light and dark"],
                [f"{settings.SITE_URL}/project/7/visual_review/repos/abc/flakiness#preset=quarantined&q={_STORY_ID}"],
            ),
            (
                "",
                "Expires *Thursday*",
                [f"*{_STORY_ID}--light* storybook", f"*{_STORY_ID}--dark* storybook"],
                [
                    f"{settings.SITE_URL}/project/7/visual_review/repos/abc/storybook/snapshots/{_STORY_ID}--light",
                    f"{settings.SITE_URL}/project/7/visual_review/repos/abc/storybook/snapshots/{_STORY_ID}--dark",
                ],
            ),
        ],
    )
    def test_theme_variants_of_a_story_expiring_together_list_once(
        self, browser_suffix: str, dark_facts: str, titles: list[str], urls: list[str]
    ) -> None:
        light = _item(_PLACED, identifier=f"{_STORY_ID}--light{browser_suffix}", facts="Expires *Wednesday*")
        dark = _item(_PLACED, identifier=f"{_STORY_ID}--dark{browser_suffix}", facts=dark_facts)
        digest = debt_digest.TeamDigest(
            team_slug="team-devex",
            expiring_quarantines=[light, dark],
            variant_pileups=[
                _item(_PLACED, identifier=f"{_STORY_ID}--light{browser_suffix}"),
                _item(_PLACED, identifier=f"{_STORY_ID}--dark{browser_suffix}"),
            ],
        )

        quarantines, pileups = debt_digest.thread_messages(_repo(), digest, _MONDAY)

        assert [text.split("\n")[0] for text in _section_texts(quarantines)[1:]] == titles
        assert [button["url"] for button in _buttons(quarantines)] == urls
        # A baseline resets one snapshot at a time, so pile-up variants keep a button each.
        assert len(_buttons(pileups)) == 2

    def test_a_group_over_the_block_limit_splits_and_repeats_its_heading(self) -> None:
        items = [_item(_PLACED)] * (debt_digest._ITEMS_PER_MESSAGE + 1)
        digest = debt_digest.TeamDigest(team_slug="team-devex", expiring_quarantines=items, variant_pileups=[])

        messages = debt_digest.thread_messages(_repo(), digest, _MONDAY)

        assert len(messages) == 2
        assert all(len(message.blocks) <= MAX_BLOCKS for message in messages)
        assert all(_section_texts(message)[0].startswith("*Quarantines expiring soon*") for message in messages)
        # Every item is carried once, under a heading that says what the reader is looking at.
        assert sum(len(_section_texts(message)) - 1 for message in messages) == len(items)

    def test_the_fallback_of_a_full_message_stays_under_the_slack_cap(self) -> None:
        items = [_item(_PLACED, line="x" * debt_digest._MAX_LINE_CHARS)] * debt_digest._ITEMS_PER_MESSAGE
        digest = debt_digest.TeamDigest(team_slug="team-devex", expiring_quarantines=items, variant_pileups=[])

        messages = debt_digest.thread_messages(_repo(), digest, _MONDAY)

        assert len(items) * debt_digest._MAX_LINE_CHARS > MAX_TEXT_CHARS
        assert len(messages) == 1
        assert len(messages[0].text) <= MAX_TEXT_CHARS


class TestMaintainersMessage:
    def test_it_lists_each_unowned_reason_with_the_action_it_asks_for(self) -> None:
        digest = _maintainers_digest(
            debt_digest.TriageGroup(
                kind=debt_digest.AttributionKind.PLACED,
                # Both themes of one story share the file, so they list once with one file button.
                items=[
                    _item(_PLACED, identifier=f"{_STORY_ID}--light"),
                    _item(_PLACED, identifier=f"{_STORY_ID}--dark"),
                ],
            ),
            debt_digest.TriageGroup(
                kind=debt_digest.AttributionKind.STORY_ABSENT,
                items=[_item(_STORY_ABSENT, identifier=_ABSENT_IDENTIFIER)],
            ),
        )

        messages = debt_digest.maintainers_messages(_repo(), digest)

        assert messages[0].blocks[0]["text"]["text"] == "Unowned visual review debt in PostHog/posthog"
        assert messages[0].blocks[1]["elements"][0]["text"].startswith("2 items nobody owns yet")
        assert [(button["text"]["text"], button["url"]) for button in _all_buttons(messages)] == [
            ("Open file", f"https://github.com/PostHog/posthog/blob/HEAD/{_SOURCE_PATH}"),
            (
                "Open snapshot",
                f"{settings.SITE_URL}/project/7/visual_review/repos/abc/storybook/snapshots/{_ABSENT_IDENTIFIER}",
            ),
        ]
        # The path stays readable in the message, because it is what somebody types into owners.yaml.
        assert f"`{_SOURCE_PATH}`" in _section_texts(messages[0])[1]
        assert _section_texts(messages[0])[1].split("\n")[0] == f"*{_STORY_ID}* storybook · light and dark"

    @pytest.mark.parametrize("kinds", [(), (debt_digest.AttributionKind.UNAVAILABLE,)])
    def test_nothing_is_sent_when_no_item_asks_anybody_to_act(self, kinds: tuple) -> None:
        digest = _maintainers_digest(
            *(debt_digest.TriageGroup(kind=kind, items=[_item(_UNAVAILABLE)]) for kind in kinds)
        )

        assert debt_digest.maintainers_messages(_repo(), digest) == []

    def test_a_file_button_too_long_for_slack_is_left_out(self) -> None:
        # Each of these percent-encodes to nine characters, so the file URL outgrows the button cap
        # on its own, and Slack refuses a whole message over one oversized button.
        path = f"frontend/src/scenes/{'界' * 400}.stories.tsx"
        item = _item(debt_digest.Attribution(kind=debt_digest.AttributionKind.PLACED, source_path=path))
        digest = _maintainers_digest(debt_digest.TriageGroup(kind=debt_digest.AttributionKind.PLACED, items=[item]))

        messages = debt_digest.maintainers_messages(_repo(), digest)

        assert _all_buttons(messages) == []
        # The path is what somebody types into owners.yaml, so losing the link costs nothing else.
        assert path in _section_texts(messages[0])[1]

    def test_an_unreadable_index_is_counted_in_the_footer_and_never_listed(self) -> None:
        digest = _maintainers_digest(
            debt_digest.TriageGroup(kind=debt_digest.AttributionKind.PLACED, items=[_item(_PLACED)]),
            debt_digest.TriageGroup(
                kind=debt_digest.AttributionKind.UNAVAILABLE,
                items=[_item(_UNAVAILABLE, identifier="scenes-app-unreadable--light")],
            ),
        )

        messages = debt_digest.maintainers_messages(_repo(), digest)

        assert messages[-1].blocks[-1]["elements"][0]["text"] == (
            "1 item with no readable Storybook index this week is not listed. Ownership is read again next Monday."
        )
        assert all("scenes-app-unreadable--light" not in str(message.blocks) for message in messages)


class TestRendering:
    @pytest.mark.parametrize("run_type", ["storybook", "<!channel>"])
    def test_escapes_slack_control_characters_in_user_text(self, run_type: str) -> None:
        # A reason, an identifier and a run type are all contributor input; any of them could
        # otherwise smuggle a <!channel> mention into every owning team's channel.
        entry = MagicMock(
            identifier="Button<!channel>",
            run_type=run_type,
            reason="flaky & <!here>",
            expires_at=_MONDAY + timedelta(days=3),
            created_by_id=None,
        )
        repo = _repo()

        line = debt_digest._quarantine_line(repo, entry, {}, _MONDAY)
        facts = debt_digest._quarantine_facts(entry, {}, _MONDAY)
        item = _item(_PLACED, identifier="Button<!channel>", line=line, facts=facts)
        digest = debt_digest.TeamDigest(team_slug="team-devex", expiring_quarantines=[item], variant_pileups=[])
        rendered = str(debt_digest.thread_messages(repo, digest, _MONDAY)[0])

        assert "<!channel>" not in rendered
        assert "<!here>" not in rendered
        assert "&lt;!channel&gt;" in rendered
        assert "flaky &amp; &lt;!here&gt;" in rendered

    @pytest.mark.parametrize(
        "expires_in,expected",
        [
            (timedelta(hours=2), "today"),
            (timedelta(days=2), "Wednesday"),
            (timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS), "Sep 21"),
        ],
    )
    def test_an_expiry_reads_as_a_day_the_reader_can_plan_around(self, expires_in: timedelta, expected: str) -> None:
        # A weekday name seven days out names the day the reader is reading on, so that one dates itself.
        entry = MagicMock(reason="flaky", expires_at=_MONDAY + expires_in, created_by_id=None)

        assert debt_digest._quarantine_facts(entry, {}, _MONDAY).startswith(f"Expires *{expected}*")

    def test_links_to_the_snapshot_page_with_encoded_segments(self) -> None:
        line = debt_digest._pileup_line(_repo(), "storybook", "scenes/Button--dark", 4)

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
        repo = _repo()
        entry = MagicMock(
            identifier=identifier,
            run_type="storybook",
            reason=reason,
            expires_at=_MONDAY + timedelta(days=3),
            created_by_id=None,
        )
        line = debt_digest._quarantine_line(repo, entry, {}, _MONDAY)
        item = _item(_PLACED, identifier=identifier, line=line, facts=debt_digest._quarantine_facts(entry, {}, _MONDAY))
        digest = debt_digest.TeamDigest(team_slug="team-devex", expiring_quarantines=[item] * 2, variant_pileups=[])

        messages = debt_digest.thread_messages(repo, digest, _MONDAY)

        assert len(line) <= debt_digest._MAX_LINE_CHARS
        assert settings.SITE_URL in line
        assert ("/snapshots/" in line) == links_to_the_snapshot
        assert all(len(text) <= MAX_SECTION_CHARS for message in messages for text in _section_texts(message))


class TestSplitByTeam:
    def test_routes_a_placed_item_to_the_team_that_owns_its_file(self) -> None:
        placed = _item(_PLACED, line="placed")
        absent = _item(_STORY_ABSENT, identifier=_ABSENT_IDENTIFIER, line="absent")
        debt = debt_digest.RepoDebt(expiring_quarantines=[placed], variant_pileups=[absent])

        digests = debt_digest.split_by_team(
            debt, _ownership({_SOURCE_PATH: "team-product-analytics", _PRODUCT_PATH: "team-devex"})
        )

        # The maintainers hold the other item without it counting as debt of their own, so they get
        # no digest of their own here.
        assert [digest.team_slug for digest in digests.teams] == ["team-product-analytics"]
        assert digests.teams[0].expiring_quarantines == [placed]
        assert digests.maintainers == debt_digest.MaintainersDigest(
            team_slug="team-devex",
            groups=[debt_digest.TriageGroup(kind=debt_digest.AttributionKind.STORY_ABSENT, items=[absent])],
        )

    @pytest.mark.parametrize("attribution", [_PLACED, _STORY_ABSENT, _UNAVAILABLE])
    def test_keeps_the_three_unowned_outcomes_apart(self, attribution: debt_digest.Attribution) -> None:
        item = _item(attribution)
        debt = debt_digest.RepoDebt(expiring_quarantines=[item], variant_pileups=[])

        digests = debt_digest.split_by_team(debt, _ownership({_PRODUCT_PATH: "team-devex"}))

        assert digests.teams == []
        assert digests.maintainers is not None
        assert digests.maintainers.groups == [debt_digest.TriageGroup(kind=attribution.kind, items=[item])]

    def test_drops_an_item_nobody_owns(self) -> None:
        debt = debt_digest.RepoDebt(expiring_quarantines=[_item(_STORY_ABSENT)], variant_pileups=[])

        assert debt_digest.split_by_team(debt, _ownership({})) == debt_digest.RepoDigests(teams=[], maintainers=None)


class TestRouting:
    _CHANNELS = {
        "team-devex": SlackChannel(channel_id="C1", shared=False),
        "team-shared": SlackChannel(channel_id="C2", shared=True),
    }

    def test_a_team_that_opted_out_is_skipped(self) -> None:
        registry = {"team-devex": TeamEntry(notifications={"visual_review": False})}

        assert debt_digest.resolve_channel("team-devex", registry, self._CHANNELS) is None

    def test_a_shared_channel_is_refused(self) -> None:
        # A name match onto a shared channel would send an internal reminder out of the workspace.
        assert debt_digest.resolve_channel("team-shared", {}, self._CHANNELS) is None

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
    def test_only_repos_that_opted_in_are_in_scope_whatever_team_owns_them(self, team) -> None:
        mine = repos.create_repo(team_id=team.id, repo_external_id=77781, repo_full_name="org/mine")
        other_team = Team.objects.create(organization=team.organization, name="other")
        theirs = repos.create_repo(team_id=other_team.id, repo_external_id=77782, repo_full_name="org/theirs")
        for repo in (mine, theirs):
            repo.debt_digest_enabled = True
            repo.save(update_fields=["debt_digest_enabled"])
        repos.create_repo(team_id=team.id, repo_external_id=77783, repo_full_name="org/switched-off")

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

    @pytest.mark.parametrize(
        "expires_in,expected",
        [
            (timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS, hours=1), [_ABSENT_IDENTIFIER]),
            (timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS + 2), []),
        ],
    )
    def test_the_expiry_window_overlaps_so_two_weekly_runs_cannot_skip_one(
        self, repo, team, user, expires_in, expected
    ):
        # Two runs a week apart can fall slightly more than seven days apart, and a quarantine
        # expiring in that gap would lapse without anybody being told.
        now = timezone.now()
        quarantine.quarantine_identifier(
            repo_id=repo.id,
            identifier=_ABSENT_IDENTIFIER,
            run_type=RunType.STORYBOOK,
            reason="non-deterministic",
            user_id=user.id,
            team_id=team.id,
            expires_at=now + expires_in,
        )

        debt = debt_digest.collect_debt(repo, now)

        assert [item.identifier for item in debt.expiring_quarantines] == expected

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
        # Preview prints the plain text behind every message, so a by-hand run reads without Slack.
        assert rendered[0].startswith("Visual review debt for team-devex in org/test-debt: ")
        assert "3 accepted variants of the current baseline" in rendered[0]
        assert rendered[0].rstrip().split("\n")[-1].startswith("Next digest Monday, ")

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
        self._completed_run(repo, mocker, (_IDENTIFIER, _OTHER_IDENTIFIER))
        self._pile_up(repo)
        self._pile_up(repo, identifier=_OTHER_IDENTIFIER)
        index = story_index.StoryIndex(path_by_story_id={_STORY_ID: _SOURCE_PATH, _OTHER_STORY_ID: _OTHER_PATH})
        with (
            _with_index(index),
            patch(
                "products.visual_review.backend.logic.debt_digest.resolve_path_owners",
                return_value=_ownership({_SOURCE_PATH: "team-one", _OTHER_PATH: "team-two", _PRODUCT_PATH: "team-two"}),
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
