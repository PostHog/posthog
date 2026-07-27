import json

from posthog.test.base import BaseTest
from unittest import TestCase

from parameterized import parameterized

from posthog import redis

from products.notebooks.backend.collab import StepEntry, submit_steps
from products.notebooks.backend.collab_stream import STREAM_KEY_PATTERN, STREAM_MAX_LENGTH
from products.notebooks.backend.markdown_collab import (
    MAX_PUBLISHED_DIFF_BYTES,
    MarkdownDiff,
    apply_utf16_text_changes,
    build_markdown_update_diff,
    fetch_missed_markdown_updates,
    get_markdown_notebook_markdown,
    markdown_crc,
    publish_notebook_update,
    submit_markdown_update,
    utf16_single_span_diff,
)
from products.notebooks.backend.presence import PRESENCE_STREAM_KEY_PATTERN, PRESENCE_TTL_SECONDS, publish_presence


def markdown_doc(markdown: str) -> dict:
    return {
        "type": "doc",
        "content": [{"type": "ph-markdown-notebook", "attrs": {"nodeId": "n1", "markdown": markdown}}],
    }


class TestNotebookCollab(BaseTest):
    def test_submit_to_empty_stream_seeds_position_from_caller(self):
        # No init endpoint anymore — first writer trusts last_seen_version (loaded from Postgres).
        result = submit_steps(
            self.team.pk,
            "nb1",
            "client1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            5,
            last_saved_version=5,
        )
        assert result.status == "accepted"
        assert result.version == 6

    def test_submit_steps_accepted(self):
        result = submit_steps(
            self.team.pk,
            "nb3",
            "client1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            0,
            last_saved_version=0,
        )
        assert result.status == "accepted"
        assert result.version == 1

    def test_submit_steps_rejected_on_version_mismatch(self):
        submit_steps(
            self.team.pk,
            "nb4",
            "client1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            0,
            last_saved_version=0,
        )
        result = submit_steps(
            self.team.pk,
            "nb4",
            "client2",
            [{"stepType": "replace", "from": 1, "to": 1}],
            0,
            last_saved_version=1,
        )
        assert result.status == "conflict"
        assert result.version == 1
        assert result.steps_since == [
            StepEntry(step={"stepType": "replace", "from": 0, "to": 0}, client_id="client1"),
        ]

    def test_submit_multiple_steps_as_batch(self):
        steps = [
            {"stepType": "replace", "from": 0, "to": 0},
            {"stepType": "replace", "from": 1, "to": 1},
            {"stepType": "replace", "from": 2, "to": 2},
        ]
        result = submit_steps(self.team.pk, "nb5", "client1", steps, 0, last_saved_version=0)
        assert result.status == "accepted"
        assert result.version == 3

    @parameterized.expand(
        [
            ("two_clients_sequential", "nb_multi_2", 2),
            ("three_clients_sequential", "nb_multi_3", 3),
        ]
    )
    def test_multiple_clients_sequential(self, _name, notebook_id, num_clients):
        expected_version = 0
        for i in range(num_clients):
            result = submit_steps(
                self.team.pk,
                notebook_id,
                f"client{i}",
                [{"stepType": "replace", "from": i, "to": i}],
                expected_version,
                last_saved_version=expected_version,
            )
            assert result.status == "accepted"
            expected_version += 1

        assert expected_version == num_clients

    def test_submit_steps_returns_stale_when_stream_trimmed(self):
        submit_steps(
            self.team.pk,
            "nb_trimmed",
            "client1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            0,
            last_saved_version=0,
        )
        submit_steps(
            self.team.pk,
            "nb_trimmed",
            "client1",
            [{"stepType": "replace", "from": 1, "to": 1}],
            1,
            last_saved_version=1,
        )

        client = redis.get_client()
        # Force-trim past version 1 to simulate MAXLEN/TTL eviction; version 2 (id 2-0) survives.
        client.xtrim(
            STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id="nb_trimmed"),
            minid="2-0",
        )

        result = submit_steps(
            self.team.pk,
            "nb_trimmed",
            "client2",
            [{"stepType": "replace", "from": 2, "to": 2}],
            0,
            last_saved_version=2,
        )
        assert result.status == "stale"
        assert result.version == 2
        assert result.steps_since is None

    def test_empty_stream_with_stale_client_baseline_returns_stale(self):
        # Stream lost (e.g. TTL expired) — Postgres still has the high version. A stale tab whose
        # baseline doesn't match Postgres must not be accepted; otherwise its save would
        # overwrite Postgres with a lower version. Client must reload from Postgres.
        result = submit_steps(
            self.team.pk,
            "nb_stale_after_expiry",
            "client_stale",
            [{"stepType": "replace", "from": 0, "to": 0}],
            last_seen_version=937,
            last_saved_version=946,
        )
        assert result.status == "stale"
        assert result.version == 946
        assert result.steps_since is None

    def test_empty_stream_with_client_ahead_of_postgres_returns_stale(self):
        # Defensive: even if the client is somehow ahead of Postgres (legacy PATCH path went
        # backwards, Postgres restore, etc.) we still cannot rebase against an empty stream.
        result = submit_steps(
            self.team.pk,
            "nb_client_ahead",
            "client_ahead",
            [{"stepType": "replace", "from": 0, "to": 0}],
            last_seen_version=946,
            last_saved_version=937,
        )
        assert result.status == "stale"
        assert result.version == 937
        assert result.steps_since is None

    def test_empty_stream_with_matching_postgres_accepts(self):
        # The legitimate first save after a Redis flush: client baseline matches Postgres so
        # the empty stream is safely seeded from there.
        result = submit_steps(
            self.team.pk,
            "nb_first_save_after_flush",
            "client1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            last_seen_version=946,
            last_saved_version=946,
        )
        assert result.status == "accepted"
        assert result.version == 947

    def test_non_empty_lagging_stream_with_postgres_matching_baseline_resyncs(self):
        # Failed XADDs (publish errors are swallowed) can leave the stream behind Postgres.
        # When the client's baseline matches Postgres, the save is accepted and the stream
        # resyncs forward — otherwise every save would wedge on a permanently lagging stream.
        submit_steps(
            self.team.pk,
            "nb_client_ahead_nonempty",
            "client1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            0,
            last_saved_version=0,
        )

        result = submit_steps(
            self.team.pk,
            "nb_client_ahead_nonempty",
            "client_resync",
            [{"stepType": "replace", "from": 1, "to": 1}],
            last_seen_version=5,
            last_saved_version=5,
        )
        assert result.status == "accepted"
        assert result.version == 6

    def test_non_empty_lagging_stream_with_mismatched_baseline_returns_stale(self):
        # Stream behind the caller AND the caller disagrees with Postgres: nothing to rebase
        # against, the client must reload.
        submit_steps(
            self.team.pk,
            "nb_client_ahead_mismatch",
            "client1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            0,
            last_saved_version=0,
        )

        result = submit_steps(
            self.team.pk,
            "nb_client_ahead_mismatch",
            "client_stale",
            [{"stepType": "replace", "from": 1, "to": 1}],
            last_seen_version=5,
            last_saved_version=3,
        )
        assert result.status == "stale"
        assert result.version == 1
        assert result.steps_since is None

    def test_submit_steps_continues_after_update_event(self):
        publish_notebook_update(self.team.pk, "nb_update_event", 1)

        result = submit_steps(
            self.team.pk,
            "nb_update_event",
            "client1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            1,
            last_saved_version=1,
        )

        assert result.status == "accepted"
        assert result.version == 2

    def test_submit_steps_treats_missed_update_event_as_stale(self):
        publish_notebook_update(self.team.pk, "nb_missed_update_event", 1)

        result = submit_steps(
            self.team.pk,
            "nb_missed_update_event",
            "client1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            0,
            last_saved_version=1,
        )

        assert result.status == "stale"
        assert result.version == 1
        assert result.steps_since is None

    def test_stream_maxlen_constant_is_sane(self):
        # Sanity: MAXLEN must comfortably hold an hour of edits. Adjust deliberately if changed.
        assert STREAM_MAX_LENGTH >= 1000


class TestUtf16Diff(TestCase):
    @parameterized.expand(
        [
            ("insert_middle", "hello world", "hello brave world"),
            ("delete_middle", "hello brave world", "hello world"),
            ("replace_middle", "hello world", "hello there"),
            ("append", "hello", "hello world"),
            ("prepend", "world", "hello world"),
            ("delete_all", "hello", ""),
            ("insert_into_empty", "", "hello"),
            ("repeated_chars", "aaaa", "aaa"),
            ("emoji_replaced", "before 🦔 after", "before 🦕 after"),
            ("emoji_inserted", "before after", "before 🦔 after"),
            ("emoji_deleted", "before 🦔 after", "before after"),
            ("text_after_emoji", "🦔a", "🦔b"),
            ("only_emoji_swap_shared_high_surrogate", "🦔", "🦕"),
            ("multibyte_text", "naïve café", "naïve cafés ✨"),
        ]
    )
    def test_diff_round_trips_through_apply(self, _name, base, next_text):
        change = utf16_single_span_diff(base, next_text)
        assert change is not None
        assert apply_utf16_text_changes(base, [change]) == next_text

    def test_diff_of_equal_strings_is_none(self):
        assert utf16_single_span_diff("same", "same") is None

    def test_diff_offsets_are_utf16_code_units(self):
        # "🦔" is two UTF-16 code units, so the trailing char sits at unit offset 2.
        assert utf16_single_span_diff("🦔a", "🦔b") == {"start": 2, "end": 3, "text": "b"}

    @parameterized.expand(
        [
            ("end_beyond_base", "abc", [{"start": 0, "end": 4, "text": "x"}]),
            ("start_after_end", "abc", [{"start": 2, "end": 1, "text": "x"}]),
            (
                "overlapping_changes",
                "abcdef",
                [{"start": 0, "end": 3, "text": "x"}, {"start": 2, "end": 4, "text": "y"}],
            ),
            ("non_numeric_offsets", "abc", [{"start": "0", "end": 1, "text": "x"}]),
            ("missing_text", "abc", [{"start": 0, "end": 1}]),
        ]
    )
    def test_apply_rejects_invalid_changes(self, _name, base, changes):
        assert apply_utf16_text_changes(base, changes) is None

    def test_apply_multiple_ascending_changes(self):
        assert (
            apply_utf16_text_changes(
                "abcdef", [{"start": 0, "end": 1, "text": "X"}, {"start": 3, "end": 5, "text": "Y"}]
            )
            == "XbcYf"
        )

    @parameterized.expand(
        [
            ("empty", "", 0),
            ("ascii", "hello", 1427272415),
            ("emoji", "# Title\n\nSome text 🦔", 2055511376),
            ("multibyte", "naïve café ✨", 591606638),
        ]
    )
    def test_markdown_crc_vectors(self, _name, text, expected):
        # Shared vectors with collaboration.test.ts — both sides hash UTF-16-LE bytes.
        assert markdown_crc(text) == expected


class TestBuildMarkdownUpdateDiff(TestCase):
    def test_returns_changes_and_base_crc(self):
        diff = build_markdown_update_diff(markdown_doc("hello world"), markdown_doc("hello brave world"))
        assert diff is not None
        assert apply_utf16_text_changes("hello world", diff.changes) == "hello brave world"
        assert diff.base_crc == markdown_crc("hello world")

    @parameterized.expand(
        [
            ("equal_markdown", markdown_doc("same"), markdown_doc("same")),
            ("previous_not_markdown", {"type": "doc", "content": []}, markdown_doc("hello")),
            ("next_not_markdown", markdown_doc("hello"), {"type": "doc", "content": []}),
            ("previous_none", None, markdown_doc("hello")),
        ]
    )
    def test_returns_none_when_not_diffable(self, _name, previous_content, next_content):
        assert build_markdown_update_diff(previous_content, next_content) is None

    def test_returns_none_when_diff_too_large(self):
        huge = "x" * (MAX_PUBLISHED_DIFF_BYTES + 1)
        assert build_markdown_update_diff(markdown_doc(""), markdown_doc(huge)) is None

    @parameterized.expand(
        [
            ("markdown", markdown_doc("# Hi"), "# Hi"),
            ("not_a_dict", "nope", None),
            ("rich_doc", {"type": "doc", "content": [{"type": "paragraph"}]}, None),
            ("two_nodes", {"type": "doc", "content": [markdown_doc("a")["content"][0]] * 2}, None),
            (
                "markdown_not_string",
                {"type": "doc", "content": [{"type": "ph-markdown-notebook", "attrs": {"markdown": 5}}]},
                None,
            ),
        ]
    )
    def test_get_markdown_notebook_markdown(self, _name, content, expected):
        assert get_markdown_notebook_markdown(content) == expected


class TestMarkdownCollabStream(BaseTest):
    def test_submit_markdown_update_accepted(self):
        diff = MarkdownDiff(changes=[{"start": 0, "end": 0, "text": "hi"}], base_crc=markdown_crc(""))
        result = submit_markdown_update(
            self.team.pk, "md1", client_id="client1", diff=diff, last_seen_version=0, last_saved_version=0
        )
        assert result.status == "accepted"
        assert result.version == 1

    def test_submit_at_old_baseline_returns_missed_updates_in_order(self):
        base = ""
        for i, text in enumerate(["one", "one two", "one two three"]):
            change = utf16_single_span_diff(base, text)
            assert change is not None
            diff = MarkdownDiff(changes=[change], base_crc=markdown_crc(base))
            result = submit_markdown_update(
                self.team.pk, "md2", client_id=f"client{i}", diff=diff, last_seen_version=i, last_saved_version=i
            )
            assert result.status == "accepted"
            base = text

        result = submit_markdown_update(
            self.team.pk,
            "md2",
            client_id="client_behind",
            diff=MarkdownDiff(changes=[{"start": 0, "end": 0, "text": "x"}], base_crc=markdown_crc("one")),
            last_seen_version=1,
            last_saved_version=3,
        )
        assert result.status == "conflict"
        assert result.version == 3
        assert result.updates is not None
        assert [entry.version for entry in result.updates] == [2, 3]

        # Folding the replayed diffs reconstructs the server state exactly
        markdown = "one"
        for entry in result.updates:
            assert entry.base_crc == markdown_crc(markdown)
            applied = apply_utf16_text_changes(markdown, entry.diff)
            assert applied is not None
            markdown = applied
        assert markdown == "one two three"

    def test_missed_range_with_diffless_ping_is_stale(self):
        submit_markdown_update(
            self.team.pk,
            "md3",
            client_id="client1",
            diff=MarkdownDiff(changes=[{"start": 0, "end": 0, "text": "a"}], base_crc=markdown_crc("")),
            last_seen_version=0,
            last_saved_version=0,
        )
        publish_notebook_update(self.team.pk, "md3", 2)

        result = submit_markdown_update(
            self.team.pk,
            "md3",
            client_id="client2",
            diff=None,
            last_seen_version=0,
            last_saved_version=2,
        )
        assert result.status == "stale"
        assert result.version == 2

    def test_missed_range_with_prosemirror_step_is_stale(self):
        submit_steps(
            self.team.pk,
            "md4",
            "pm_client",
            [{"stepType": "replace", "from": 0, "to": 0}],
            0,
            last_saved_version=0,
        )

        result = submit_markdown_update(
            self.team.pk,
            "md4",
            client_id="md_client",
            diff=None,
            last_seen_version=0,
            last_saved_version=1,
        )
        assert result.status == "stale"
        assert result.version == 1

    def test_published_update_with_diff_is_replayable(self):
        # The legacy PATCH path publishes `{version}-1` entries; they must replay like CAS entries.
        diff = MarkdownDiff(changes=[{"start": 0, "end": 0, "text": "hello"}], base_crc=markdown_crc(""))
        publish_notebook_update(self.team.pk, "md5", 1, diff=diff)

        result = fetch_missed_markdown_updates(self.team.pk, "md5", last_seen_version=0, current_version=1)
        assert result.status == "conflict"
        assert result.updates is not None
        assert result.updates[0].version == 1
        assert result.updates[0].diff == diff.changes
        assert result.updates[0].base_crc == diff.base_crc
        assert result.updates[0].client_id is None

    def test_submit_after_published_update_continues_version_sequence(self):
        diff = MarkdownDiff(changes=[{"start": 0, "end": 0, "text": "hello"}], base_crc=markdown_crc(""))
        publish_notebook_update(self.team.pk, "md6", 1, diff=diff)

        result = submit_markdown_update(
            self.team.pk,
            "md6",
            client_id="client1",
            diff=MarkdownDiff(changes=[{"start": 5, "end": 5, "text": "!"}], base_crc=markdown_crc("hello")),
            last_seen_version=1,
            last_saved_version=1,
        )
        assert result.status == "accepted"
        assert result.version == 2

    def test_fetch_with_current_at_or_below_baseline_is_stale(self):
        result = fetch_missed_markdown_updates(self.team.pk, "md7", last_seen_version=5, current_version=5)
        assert result.status == "stale"

    def test_submit_markdown_update_carries_author_presence(self):
        diff = MarkdownDiff(changes=[{"start": 0, "end": 0, "text": "hi"}], base_crc=markdown_crc(""))
        result = submit_markdown_update(
            self.team.pk,
            "md8",
            client_id="client1",
            diff=diff,
            last_seen_version=0,
            last_saved_version=0,
            user_id=42,
            user_name="Ada Lovelace",
            cursor={"node_index": 0, "offset": 2},
        )
        assert result.status == "accepted"

        client = redis.get_client()
        entries = client.xrange(STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id="md8"))
        payload = json.loads(entries[0][1][b"data"])
        assert payload["user_id"] == 42
        assert payload["user_name"] == "Ada Lovelace"
        assert payload["cursor"] == {"node_index": 0, "offset": 2}

        # Presence extras must not break diff replay for conflicting writers
        replay = fetch_missed_markdown_updates(self.team.pk, "md8", last_seen_version=0, current_version=1)
        assert replay.status == "conflict"

    def test_submit_markdown_update_without_presence_omits_fields(self):
        diff = MarkdownDiff(changes=[{"start": 0, "end": 0, "text": "hi"}], base_crc=markdown_crc(""))
        submit_markdown_update(
            self.team.pk, "md9", client_id="client1", diff=diff, last_seen_version=0, last_saved_version=0
        )

        client = redis.get_client()
        entries = client.xrange(STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id="md9"))
        payload = json.loads(entries[0][1][b"data"])
        assert "user_id" not in payload
        assert "user_name" not in payload
        assert "cursor" not in payload


class TestPresenceStream(BaseTest):
    def test_publish_presence_appends_entry_with_ttl(self):
        publish_presence(
            self.team.pk,
            "pr1",
            client_id="client1",
            user_id=7,
            user_name="Grace Hopper",
            version=3,
            cursor={"head": 12},
        )

        client = redis.get_client()
        stream_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id="pr1")
        entries = client.xrange(stream_key)
        assert len(entries) == 1
        payload = json.loads(entries[0][1][b"data"])
        assert payload == {
            "type": "presence",
            "client_id": "client1",
            "user_id": 7,
            "user_name": "Grace Hopper",
            "version": 3,
            "cursor": {"head": 12},
        }
        assert 0 < client.ttl(stream_key) <= PRESENCE_TTL_SECONDS

    def test_presence_stream_is_separate_from_content_stream(self):
        publish_presence(
            self.team.pk,
            "pr2",
            client_id="client1",
            user_id=7,
            user_name="Grace Hopper",
            version=0,
            cursor={"head": 0},
        )

        client = redis.get_client()
        assert client.xrange(STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id="pr2")) == []
