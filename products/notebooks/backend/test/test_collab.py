from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog import redis

from products.notebooks.backend.collab import STREAM_KEY_PATTERN, STREAM_MAX_LENGTH, StepEntry, submit_steps


class TestNotebookCollab(BaseTest):
    def test_submit_to_empty_stream_seeds_position_from_caller(self):
        # No init endpoint anymore — first writer trusts last_seen_version (loaded from Postgres).
        result = submit_steps(self.team.pk, "nb1", "client1", [{"stepType": "replace", "from": 0, "to": 0}], 5)
        assert result.status == "accepted"
        assert result.version == 6

    def test_submit_steps_accepted(self):
        result = submit_steps(self.team.pk, "nb3", "client1", [{"stepType": "replace", "from": 0, "to": 0}], 0)
        assert result.status == "accepted"
        assert result.version == 1

    def test_submit_steps_rejected_on_version_mismatch(self):
        submit_steps(self.team.pk, "nb4", "client1", [{"stepType": "replace", "from": 0, "to": 0}], 0)
        result = submit_steps(self.team.pk, "nb4", "client2", [{"stepType": "replace", "from": 1, "to": 1}], 0)
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
        result = submit_steps(self.team.pk, "nb5", "client1", steps, 0)
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
            )
            assert result.status == "accepted"
            expected_version += 1

        assert expected_version == num_clients

    def test_submit_steps_returns_stale_when_stream_trimmed(self):
        submit_steps(self.team.pk, "nb_trimmed", "client1", [{"stepType": "replace", "from": 0, "to": 0}], 0)
        submit_steps(self.team.pk, "nb_trimmed", "client1", [{"stepType": "replace", "from": 1, "to": 1}], 1)

        client = redis.get_client()
        # Force-trim past version 1 to simulate MAXLEN/TTL eviction; version 2 (id 2-0) survives.
        client.xtrim(
            STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id="nb_trimmed"),
            minid="2-0",
        )

        result = submit_steps(self.team.pk, "nb_trimmed", "client2", [{"stepType": "replace", "from": 2, "to": 2}], 0)
        assert result.status == "stale"
        assert result.version == 2
        assert result.steps_since is None

    def test_stream_maxlen_constant_is_sane(self):
        # Sanity: MAXLEN must comfortably hold an hour of edits. Adjust deliberately if changed.
        assert STREAM_MAX_LENGTH >= 1000
