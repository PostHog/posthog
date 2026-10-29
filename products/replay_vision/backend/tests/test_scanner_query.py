from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort
from products.replay_vision.backend.scanner_query import (
    MAX_QUERY_BYTES,
    NarrowingRefusal,
    narrow_chosen_query,
    unresolved_references,
)

_CHOSEN: dict[str, Any] = {
    "kind": "RecordingsQuery",
    "properties": [{"type": "recording", "key": "visited_page", "value": "/billing", "operator": "icontains"}],
}
_EVENT = {"id": "billing_limit_set", "name": "billing_limit_set", "type": "events", "order": 0}


class TestNarrowChosenQuery:
    @parameterized.expand(
        [
            # An OR on either side would join the additions with an OR and widen the scan.
            (
                "chosen OR",
                {**_CHOSEN, "operand": "OR"},
                {"kind": "RecordingsQuery", "events": [_EVENT]},
                NarrowingRefusal.OR_OPERAND,
            ),
            # The query builder reads anything but AND, an explicit null included, as OR.
            (
                "chosen null operand",
                {**_CHOSEN, "operand": None},
                {"kind": "RecordingsQuery", "events": [_EVENT]},
                NarrowingRefusal.OR_OPERAND,
            ),
            (
                "drafted OR",
                _CHOSEN,
                {"kind": "RecordingsQuery", "events": [_EVENT, {**_EVENT, "id": "plan_upgraded"}], "operand": "OR"},
                NarrowingRefusal.OR_OPERAND,
            ),
            # A saved scanner must meet the size cap, so a proposal that breaks it is not one it can keep.
            (
                "too large to save",
                _CHOSEN,
                {
                    "kind": "RecordingsQuery",
                    "events": [{**_EVENT, "id": f"event_{i}_{'x' * 500}"} for i in range(MAX_QUERY_BYTES // 500)],
                },
                NarrowingRefusal.INVALID,
            ),
            # Nothing new is no proposal, so there is nothing to refuse.
            ("repeat only", _CHOSEN, {"kind": "RecordingsQuery", "properties": _CHOSEN["properties"]}, None),
            ("nothing drafted", _CHOSEN, None, None),
        ]
    )
    def test_keeps_the_chosen_query_when_it_cannot_be_narrowed(self, _name, chosen, proposed, refusal):
        narrowing = narrow_chosen_query(chosen, proposed)

        assert (narrowing.query, narrowing.additions, narrowing.refusal) == (chosen, None, refusal)

    def test_ands_new_conditions_and_reports_only_those(self):
        proposed = {"kind": "RecordingsQuery", "properties": _CHOSEN["properties"], "events": [_EVENT]}

        narrowing = narrow_chosen_query(_CHOSEN, proposed)

        assert narrowing.query == {**_CHOSEN, "events": [_EVENT]}
        assert narrowing.additions == {"kind": "RecordingsQuery", "events": [_EVENT]}
        assert narrowing.refusal is None


class TestUnresolvedReferences(BaseTest):
    def test_names_the_references_a_scan_cannot_load(self):
        # The recordings query builder skips deleted cohorts and fails on missing actions, so both would
        # make every estimate and every run of the scanner fail.
        live_action = Action.objects.create(team=self.team, name="Completed checkout")
        live_cohort = Cohort.objects.create(team=self.team, name="Paying customers")
        deleted_cohort = Cohort.objects.create(team=self.team, name="Old customers", deleted=True)
        query = {
            "kind": "RecordingsQuery",
            "actions": [{"id": live_action.id, "type": "actions"}, {"id": 999999, "type": "actions"}],
            "properties": [
                {"type": "cohort", "key": "id", "value": live_cohort.id, "operator": "in"},
                {"type": "cohort", "key": "id", "value": deleted_cohort.id, "operator": "in"},
                {"type": "cohort", "key": "id", "value": "not-an-id", "operator": "in"},
            ],
        }

        assert unresolved_references(query, self.team) == [
            "action 999999",
            f"cohort {deleted_cohort.id}",
            "cohort not-an-id",
        ]
