from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort
from products.replay_vision.backend.scanner_query import (
    MAX_QUERY_BYTES,
    NarrowingRefusal,
    QueryReferences,
    ScannerQueryError,
    chosen_scope,
    narrow_chosen_query,
    query_references,
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


class TestChosenScope:
    @parameterized.expand(
        [
            ("every variant", {}, None),
            # An empty name is a variant to check against the experiment, not a request for every variant.
            ("an empty variant name", {"variant": ""}, [""]),
            ("repeated variants", {"variants": ["test", "control", "test"]}, ["test", "control"]),
        ]
    )
    def test_reads_the_exposure_variants_the_way_the_replay_list_does(self, _name, variant_fields, expected):
        exposure = {"experiment_id": 1, **variant_fields}

        scope = chosen_scope({"kind": "RecordingsQuery", "experiment_exposure": exposure}, experiment_id=None)

        assert scope.experiment_variants == expected


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
            ],
        }

        assert unresolved_references(query, self.team) == ["action 999999", f"cohort {deleted_cohort.id}"]

    def test_finds_references_in_every_shape_the_query_builder_runs(self):
        # Each of these runs as an action or cohort filter, so a reference read off the raw JSON would let
        # a caller without read access use the entity unchecked.
        query = {
            "kind": "RecordingsQuery",
            "events": [
                {"id": 901, "type": "actions"},
                {
                    "id": "$pageview",
                    "type": "events",
                    "properties": {"type": "AND", "values": [{"type": "cohort", "key": "id", "value": 902}]},
                },
            ],
            "properties": [
                {"value": 903},
                {"type": "hogql", "key": "matchesAction(904) AND person_id NOT IN COHORT 905"},
            ],
        }

        assert query_references(query, self.team) == QueryReferences(actions=[901, 904], cohorts=[902, 903, 905])

    @parameterized.expand(
        [
            ("a non-numeric action id", {"actions": [{"id": float("inf")}]}),
            # Resolving a name here would tell the caller which id it has before any access check.
            ("an action named in HogQL", {"properties": [{"type": "hogql", "key": "matchesAction('Signed up')"}]}),
            ("a cohort named in HogQL", {"properties": [{"type": "hogql", "key": "person_id IN COHORT 'Paying'"}]}),
            # A subquery can select from the cohort tables directly, where no reference is visible.
            (
                "a HogQL subquery",
                {"properties": [{"type": "hogql", "key": "person_id IN (SELECT person_id FROM cohort_people)"}]},
            ),
        ]
    )
    def test_refuses_references_it_cannot_read(self, _name, filters):
        with self.assertRaises(ScannerQueryError):
            query_references({"kind": "RecordingsQuery", **filters}, self.team)
