from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import User
from posthog.models.scoping import team_scope

from products.posthog_ai.backend.turn_suggestions.offer_ledger import STATE_KEY, OfferRecord, OfferStatus, read_ledger
from products.tasks.backend.facade.contracts import StreamNotificationDelivery
from products.tasks.backend.models import Channel, Task

SERVICE = "products.posthog_ai.backend.turn_suggestions.service"


def _offer(turn_index: int, *, run_id: str) -> dict:
    return OfferRecord(turn_index=turn_index, run_id=run_id, kind="scout", status=OfferStatus.OFFERED).to_json()


class TestResolveTurnSuggestion(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        self.task_run = self.task.create_run(mode="interactive")
        Task.objects.filter(id=self.task.id).update(
            state={STATE_KEY: {"offers": [_offer(0, run_id=str(self.task_run.id))]}}
        )

    def _resolve(self, task_id: str, turn_index: int, resolution: str, *, live: bool = True):
        delivery = StreamNotificationDelivery(live=live, persisted=False)
        with patch(f"{SERVICE}.publish_task_run_stream_notification", return_value=delivery) as publish:
            response = self.client.post(
                f"/api/projects/{self.team.id}/turn_suggestions/resolve/",
                {"task_id": task_id, "turn_index": turn_index, "resolution": resolution},
                format="json",
            )
        return response, publish

    def _state(self, task_id: str):
        return self.client.get(f"/api/projects/{self.team.id}/turn_suggestions/state/", {"task_id": task_id})

    @parameterized.expand(
        [
            ("other_tabs_reached", True, False),
            ("no_tab_listening", False, False),
            ("warmed_successor_run", True, True),
        ]
    )
    def test_a_dismissal_mutes_the_conversation_and_a_reload_reads_it(
        self, _name: str, live: bool, with_successor: bool
    ):
        run_ids = {str(self.task_run.id)}
        if with_successor:
            run_ids.add(str(self.task.create_run(mode="interactive").id))

        response, publish = self._resolve(str(self.task.id), 0, "dismissed", live=live)

        assert response.status_code == 200
        assert response.json() == {"recorded": True}
        assert self._state(str(self.task.id)).json() == {"muted": True, "resolved_turns": [0]}
        assert {call.args[0] for call in publish.call_args_list} == run_ids
        for call in publish.call_args_list:
            assert call.args[1:] == (
                str(self.task.id),
                self.team.id,
                "_posthog/turn_suggestion_resolved",
                {"turnIndex": 0, "outcome": "dismissed"},
            )
            assert call.kwargs == {"persist": False}

    def test_a_card_keeps_its_first_outcome(self):
        self._resolve(str(self.task.id), 0, "accepted")

        response, publish = self._resolve(str(self.task.id), 0, "dismissed")

        assert response.json() == {"recorded": False}
        publish.assert_not_called()
        ledger = read_ledger(self.task.id, self.team.id)
        assert ledger.offers[0].status == OfferStatus.ACCEPTED
        assert ledger.muted is False

    @parameterized.expand(
        [
            ("turn_without_a_card", "own_task", 3, 200),
            ("task_of_another_team", "other_team", 0, 404),
            ("teammate_task_readable_in_a_shared_channel", "read_only", 0, 404),
        ]
    )
    def test_nothing_is_recorded_for_a_card_that_does_not_exist(
        self, _name: str, task_access: str, turn_index: int, status_code: int
    ):
        task_id = str(self.task.id)
        if task_access == "other_team":
            other = self.create_team_with_organization(organization=self.organization)
            task_id = str(
                Task.objects.create(
                    team=other,
                    title="t",
                    description="d",
                    origin_product=Task.OriginProduct.POSTHOG_AI,
                    created_by=self.user,
                ).id
            )
        elif task_access == "read_only":
            creator = User.objects.create_and_join(self.organization, "creator@example.com", "password")
            with team_scope(self.team.id):
                shared = Channel.objects.create(team=self.team, name="general", created_by=creator)
            Task.objects.filter(id=self.task.id).update(channel=shared, created_by=creator)

        response, publish = self._resolve(task_id, turn_index, "accepted")

        assert response.status_code == status_code
        publish.assert_not_called()
        if task_access == "other_team":
            assert self._state(task_id).status_code == 404
        assert read_ledger(self.task.id, self.team.id).offers[0].status == OfferStatus.OFFERED
