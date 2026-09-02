from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.temporal.babysit_pr.snapshot import (
    CONFLICT_KEY,
    AttentionSet,
    BabysitJournal,
    CommentItem,
    FailingCheck,
    PRSnapshot,
    ReviewThreadItem,
)


def make_snapshot(**overrides: object) -> PRSnapshot:
    defaults: dict = {
        "pr_url": "https://github.com/acme/widgets/pull/7",
        "pr_state": "open",
        "head_sha": "head1",
        "author_login": "posthog-bot",
    }
    defaults.update(overrides)
    return PRSnapshot(**defaults)


THREAD = ReviewThreadItem(id="T1", last_comment_id="C1", author="reviewer", body_excerpt="rename this")
CHECK = FailingCheck(key="CI/backend")
COMMENT = CommentItem(id="M1", author="coderabbit", body_excerpt="3 nits")


class TestBabysitJournal(SimpleTestCase):
    @parameterized.expand(
        [
            ("fresh_thread", BabysitJournal(), True),
            ("acted_on_the_same_comment", BabysitJournal(threads={"T1": "C1"}), False),
            ("reviewer_replied_since", BabysitJournal(threads={"T1": "C0"}), True),
        ]
    )
    def test_thread_stays_silent_until_its_last_comment_changes(self, _name, journal, expected_actionable):
        attention = journal.attention(make_snapshot(unresolved_threads=[THREAD]))
        assert (len(attention.threads) == 1) is expected_actionable

    def test_thread_last_answered_by_the_pr_author_is_never_actionable(self):
        thread = ReviewThreadItem(id="T1", last_comment_id="C2", author="posthog-bot")
        attention = BabysitJournal(threads={"T1": "C1"}).attention(make_snapshot(unresolved_threads=[thread]))
        assert attention.threads == []

    @parameterized.expand(
        [
            ("fresh_comment", BabysitJournal(), True),
            ("already_dispatched", BabysitJournal(comment_ids=["M1"]), False),
        ]
    )
    def test_comment_is_dispatched_at_most_once(self, _name, journal, expected_actionable):
        attention = journal.attention(make_snapshot(comments=[COMMENT]))
        assert (len(attention.comments) == 1) is expected_actionable

    @parameterized.expand(
        [
            ("undispatched_check_fires", BabysitJournal(), "head1", True),
            ("same_head_is_silent", BabysitJournal(head_sha="head1", head_keys=["CI/backend"]), "head1", False),
            ("new_head_reactivates", BabysitJournal(head_sha="head1", head_keys=["CI/backend"]), "head2", True),
        ]
    )
    def test_check_dedup_is_head_scoped(self, _name, journal, head_sha, expected_actionable):
        attention = journal.attention(make_snapshot(head_sha=head_sha, failing_checks=[CHECK]))
        assert (len(attention.failing_checks) == 1) is expected_actionable

    @parameterized.expand(
        [
            ("conflict_fires", True, BabysitJournal(), True),
            ("same_head_is_silent", True, BabysitJournal(head_sha="head1", head_keys=[CONFLICT_KEY]), False),
            ("new_head_reactivates", True, BabysitJournal(head_sha="head0", head_keys=[CONFLICT_KEY]), True),
            ("no_conflict_never_fires", False, BabysitJournal(), False),
        ]
    )
    def test_conflict_dedup_is_head_scoped(self, _name, has_conflict, journal, expected):
        assert journal.attention(make_snapshot(has_conflict=has_conflict)).conflict is expected

    def test_snapshot_with_nothing_open_needs_no_attention(self):
        assert BabysitJournal().attention(make_snapshot()).is_empty

    def test_recording_a_dispatch_silences_every_item_it_covered(self):
        snapshot = make_snapshot(
            has_conflict=True,
            failing_checks=[CHECK],
            unresolved_threads=[THREAD],
            comments=[COMMENT],
        )
        journal = BabysitJournal()
        attention = journal.attention(snapshot)

        recorded = journal.record(snapshot, attention)

        assert recorded.attention(snapshot).is_empty
        assert not journal.attention(snapshot).is_empty

    def test_recording_a_new_head_drops_the_previous_heads_check_marks(self):
        first = make_snapshot(has_conflict=True, failing_checks=[CHECK])
        journal = BabysitJournal().record(first, BabysitJournal().attention(first))
        second = make_snapshot(head_sha="head2", failing_checks=[FailingCheck(key="CI/frontend")])

        recorded = journal.record(second, journal.attention(second))

        assert recorded.head_sha == "head2"
        assert recorded.head_keys == ["CI/frontend"]

    def test_recording_only_the_capped_slice_leaves_omitted_feedback_actionable(self):
        # The prompt renders only the newest N items; recording the whole attention would
        # mark the oldest, never-shown feedback as handled and it would never come back.
        threads = [ReviewThreadItem(id=f"T{i}", last_comment_id="C1", author="reviewer") for i in range(3)]
        comments = [CommentItem(id=f"M{i}", author="reviewer") for i in range(3)]
        snapshot = make_snapshot(unresolved_threads=threads, comments=comments)
        journal = BabysitJournal()

        recorded = journal.record(snapshot, journal.attention(snapshot).capped(2, 2))

        remaining = recorded.attention(snapshot)
        assert [t.id for t in remaining.threads] == ["T0"]
        assert [c.id for c in remaining.comments] == ["M0"]


class TestAttentionSetCapping(SimpleTestCase):
    def test_capped_keeps_the_newest_rendered_items_and_passes_checks_and_conflict_through(self):
        threads = [ReviewThreadItem(id=f"T{i}", last_comment_id="C1") for i in range(5)]
        comments = [CommentItem(id=f"M{i}") for i in range(5)]

        capped = AttentionSet(failing_checks=[CHECK], threads=threads, comments=comments, conflict=True).capped(2, 3)

        assert [t.id for t in capped.threads] == ["T3", "T4"]
        assert [c.id for c in capped.comments] == ["M2", "M3", "M4"]
        assert capped.failing_checks == [CHECK]
        assert capped.conflict is True
