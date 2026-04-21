from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog import redis

from products.notebooks.backend.collab import STEPS_KEY, StepEntry, initialize_collab_session, submit_steps


class TestNotebookCollab(BaseTest):
    def test_initialize_collab_session_sets_version(self):
        initialize_collab_session(self.team.pk, "nb1", 5)
        result = submit_steps(self.team.pk, "nb1", "client1", [{"stepType": "replace", "from": 0, "to": 0}], 5)
        assert result.accepted is True
        assert result.version == 6

    def test_initialize_collab_session_does_not_overwrite(self):
        initialize_collab_session(self.team.pk, "nb2", 5)
        submit_steps(self.team.pk, "nb2", "client1", [{"stepType": "replace", "from": 0, "to": 0}], 5)
        # Re-initializing must not reset the version back to 5
        initialize_collab_session(self.team.pk, "nb2", 5)
        result = submit_steps(self.team.pk, "nb2", "client2", [{"stepType": "replace", "from": 0, "to": 0}], 6)
        assert result.accepted is True
        assert result.version == 7

    def test_submit_steps_accepted(self):
        initialize_collab_session(self.team.pk, "nb3", 0)
        result = submit_steps(self.team.pk, "nb3", "client1", [{"stepType": "replace", "from": 0, "to": 0}], 0)
        assert result.accepted is True
        assert result.version == 1

    def test_submit_steps_rejected_on_version_mismatch(self):
        initialize_collab_session(self.team.pk, "nb4", 0)
        # First client advances the version
        submit_steps(self.team.pk, "nb4", "client1", [{"stepType": "replace", "from": 0, "to": 0}], 0)
        # Second client tries with stale version
        result = submit_steps(self.team.pk, "nb4", "client2", [{"stepType": "replace", "from": 1, "to": 1}], 0)
        assert result.accepted is False
        assert result.version == 1
        assert result.steps_since == [
            StepEntry(step={"stepType": "replace", "from": 0, "to": 0}, client_id="client1", v=1),
        ]

    def test_submit_multiple_steps_as_batch(self):
        initialize_collab_session(self.team.pk, "nb5", 0)
        steps = [
            {"stepType": "replace", "from": 0, "to": 0},
            {"stepType": "replace", "from": 1, "to": 1},
            {"stepType": "replace", "from": 2, "to": 2},
        ]
        result = submit_steps(self.team.pk, "nb5", "client1", steps, 0)
        assert result.accepted is True
        assert result.version == 3

    def test_submit_to_uninitialized_session(self):
        result = submit_steps(self.team.pk, "uninitialized", "client1", [{"stepType": "replace"}], 0)
        assert result.accepted is False
        assert result.version == 0

    @parameterized.expand(
        [
            ("two_clients_sequential", "nb_multi_2", 2),
            ("three_clients_sequential", "nb_multi_3", 3),
        ]
    )
    def test_multiple_clients_sequential(self, _name, notebook_id, num_clients):
        initialize_collab_session(self.team.pk, notebook_id, 0)
        expected_version = 0
        for i in range(num_clients):
            result = submit_steps(
                self.team.pk,
                notebook_id,
                f"client{i}",
                [{"stepType": "replace", "from": i, "to": i}],
                expected_version,
            )
            assert result.accepted is True
            expected_version += 1

        assert expected_version == num_clients

    def test_submit_steps_returns_none_when_steps_expired(self):
        initialize_collab_session(self.team.pk, "nb_expired", 0)
        # Advance version by submitting steps
        submit_steps(self.team.pk, "nb_expired", "client1", [{"stepType": "replace", "from": 0, "to": 0}], 0)
        submit_steps(self.team.pk, "nb_expired", "client1", [{"stepType": "replace", "from": 1, "to": 1}], 1)

        # Simulate Redis expiry by deleting the steps key
        client = redis.get_client()
        client.delete(STEPS_KEY.format(team_id=self.team.pk, notebook_id="nb_expired"))

        # Submit with stale version - version key still exists but steps are gone
        result = submit_steps(self.team.pk, "nb_expired", "client2", [{"stepType": "replace", "from": 2, "to": 2}], 0)
        assert result.accepted is False
        assert result.version == 2
        assert result.steps_since is None
