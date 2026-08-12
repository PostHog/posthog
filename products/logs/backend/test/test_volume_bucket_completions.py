import threading
from datetime import UTC, datetime

from posthog.test.base import BaseTest, NonAtomicBaseTest

from django.db import connection, transaction

from parameterized import parameterized

from products.logs.backend.models import CommittedBucket, LogsVolumeBucketCompletion, VolumeBucketGridMismatch

DAY = datetime(2026, 8, 12, tzinfo=UTC)


def _row(team_id: int, day: datetime) -> LogsVolumeBucketCompletion:
    return LogsVolumeBucketCompletion.objects.for_team(team_id).get(date=day.date())


class TestVolumeBucketCompletionProtocol(BaseTest):
    def test_commit_creates_day_row_with_leading_null_slots(self) -> None:
        generation = LogsVolumeBucketCompletion.allocate_generation()
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk, DAY.replace(hour=10, minute=35), generation)

        row = _row(self.team.pk, DAY)
        assert row.bucket_seconds == 300
        assert row.completed_generations == [None] * 127 + [generation]

    @parameterized.expand(
        [
            ("newer_after_older", 1_000, 2_000, 2_000),
            ("older_after_newer", 2_000, 1_000, 2_000),
            ("same_generation_twice", 1_500, 1_500, 1_500),
        ]
    )
    def test_slot_pointer_only_advances(self, _name: str, first: int, second: int, expected: int) -> None:
        bucket = DAY.replace(hour=6)
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk, bucket, first)
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk, bucket, second)

        assert _row(self.team.pk, DAY).completed_generations[72] == expected

    @parameterized.expand(
        [
            ("midnight_lands_in_new_day", DAY, DAY, 0),
            ("last_bucket_lands_in_same_day", DAY.replace(hour=23, minute=55), DAY, 287),
        ]
    )
    def test_day_boundary_buckets(self, _name: str, bucket: datetime, expected_day: datetime, slot: int) -> None:
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk, bucket, 1_000)

        row = _row(self.team.pk, expected_day)
        assert len(row.completed_generations) == slot + 1
        assert row.completed_generations[slot] == 1_000

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 8, 12, 10, 35), 1_000, 300),
            ("misaligned_minute", DAY.replace(hour=10, minute=2), 1_000, 300),
            ("misaligned_microsecond", DAY.replace(microsecond=1), 1_000, 300),
            ("zero_generation", DAY, 0, 300),
            ("negative_generation", DAY, -5, 300),
            ("grid_not_dividing_day", DAY, 1_000, 7),
        ]
    )
    def test_commit_rejects_invalid_input(self, _name: str, bucket: datetime, generation: int, seconds: int) -> None:
        with self.assertRaises(ValueError):
            LogsVolumeBucketCompletion.commit_bucket(self.team.pk, bucket, generation, bucket_seconds=seconds)
        assert not LogsVolumeBucketCompletion.objects.for_team(self.team.pk).exists()

    def test_commit_on_wrong_grid_raises_and_leaves_row_unchanged(self) -> None:
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk, DAY.replace(hour=6), 1_000)

        with self.assertRaises(VolumeBucketGridMismatch):
            LogsVolumeBucketCompletion.commit_bucket(self.team.pk, DAY.replace(hour=6), 2_000, bucket_seconds=600)

        row = _row(self.team.pk, DAY)
        assert row.bucket_seconds == 300
        assert row.completed_generations == [None] * 72 + [1_000]

    def test_read_returns_exactly_the_committed_pairs_across_days(self) -> None:
        day2 = datetime(2026, 8, 13, tzinfo=UTC)
        committed = [
            (DAY.replace(hour=23, minute=50), 1_001),
            (DAY.replace(hour=23, minute=55), 1_002),
            (day2, 1_003),
            (day2.replace(minute=5), 1_004),
        ]
        for bucket, generation in committed:
            LogsVolumeBucketCompletion.commit_bucket(self.team.pk, bucket, generation)
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk, DAY.replace(hour=23, minute=40), 999)
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk + 1, DAY.replace(hour=23, minute=50), 998)

        pairs = LogsVolumeBucketCompletion.read_committed_pairs(
            self.team.pk, DAY.replace(hour=23, minute=45), day2.replace(minute=5)
        )

        assert pairs == [
            CommittedBucket(time_bucket=bucket, generation=generation) for bucket, generation in committed[:3]
        ]

    def test_read_spans_a_cadence_change(self) -> None:
        day2 = datetime(2026, 8, 13, tzinfo=UTC)
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk, DAY.replace(hour=23, minute=55), 1_001)
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk, day2.replace(minute=20), 1_002, bucket_seconds=600)

        pairs = LogsVolumeBucketCompletion.read_committed_pairs(
            self.team.pk, DAY.replace(hour=23), day2.replace(hour=1)
        )

        assert pairs == [
            CommittedBucket(time_bucket=DAY.replace(hour=23, minute=55), generation=1_001),
            CommittedBucket(time_bucket=day2.replace(minute=20), generation=1_002),
        ]

    def test_read_with_empty_or_inverted_window_returns_nothing(self) -> None:
        LogsVolumeBucketCompletion.commit_bucket(self.team.pk, DAY, 1_000)

        assert LogsVolumeBucketCompletion.read_committed_pairs(self.team.pk, DAY, DAY) == []
        assert LogsVolumeBucketCompletion.read_committed_pairs(self.team.pk, DAY.replace(hour=1), DAY) == []

    def test_fully_populated_array_stays_inline_after_compression(self) -> None:
        base = LogsVolumeBucketCompletion.allocate_generation()
        LogsVolumeBucketCompletion.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            date=DAY.date(),
            completed_generations=[base + slot * 300_000 + (slot * 7_919) % 300_000 for slot in range(288)],
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT pg_column_size(completed_generations) FROM {LogsVolumeBucketCompletion._meta.db_table}"
            )
            size = cursor.fetchone()[0]
        # Raw 288x8B = 2304B crosses the 2KB TOAST threshold; the slot commits stay
        # HOT only while inline compression keeps the tuple in the heap page.
        assert size < 2_000, f"completed_generations no longer compresses inline: {size}B"


class TestVolumeBucketCompletionConcurrency(NonAtomicBaseTest):
    def test_interleaved_commits_to_the_same_day_row_both_land(self) -> None:
        team_id = self.team.pk
        thread_errors: list[Exception] = []

        def commit_other_slot() -> None:
            try:
                LogsVolumeBucketCompletion.commit_bucket(team_id, DAY.replace(hour=12), 2_000)
            except Exception as error:
                thread_errors.append(error)
            finally:
                connection.close()

        thread = threading.Thread(target=commit_other_slot)
        with transaction.atomic():
            LogsVolumeBucketCompletion.commit_bucket(team_id, DAY.replace(hour=10), 1_000)
            thread.start()
            # The second commit must block on our uncommitted row until this
            # transaction ends, so it finishing here is itself a failure: it would
            # mean the commit ran against a version without our slot.
            thread.join(timeout=1)
            assert thread.is_alive(), f"second commit finished while the row lock was held; errors={thread_errors!r}"
        thread.join(timeout=10)

        assert not thread.is_alive()
        assert thread_errors == []
        row = _row(team_id, DAY)
        assert row.completed_generations[120] == 1_000
        assert row.completed_generations[144] == 2_000
