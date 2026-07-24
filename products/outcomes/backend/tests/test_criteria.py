from datetime import UTC, datetime

import pytest

from parameterized import parameterized

from products.outcomes.backend.criteria import AtomOutcome, CriteriaValidationError, parse_criteria, resolve


def atom(event: str = "e", **overrides) -> dict:
    return {"event": event, "aggregation": "count", "threshold": 1, **overrides}


def path(*atoms: dict, min_matches: int | None = None) -> dict:
    return {"atoms": list(atoms), "min_matches": min_matches}


def criteria(*paths: dict) -> dict:
    return {"paths": list(paths)}


def ts(minute: int) -> datetime:
    return datetime(2026, 1, 1, 10, minute, tzinfo=UTC)


class TestParseCriteria:
    @parameterized.expand(
        [
            ("not_a_dict", []),
            ("no_paths", {}),
            ("empty_paths", {"paths": []}),
            ("too_many_paths", criteria(*[path(atom()) for _ in range(6)])),
            ("too_many_atoms", criteria(path(*[atom() for _ in range(6)]), path(*[atom() for _ in range(5)]))),
            ("path_without_atoms", criteria({"atoms": [], "min_matches": None})),
            ("missing_event", criteria(path({"aggregation": "count", "threshold": 1}))),
            ("loop_guard_event", criteria(path(atom("$outcome_reached")))),
            ("non_monotone_aggregation", criteria(path(atom(aggregation="avg", aggregation_property="x")))),
            ("sum_without_property", criteria(path(atom(aggregation="sum", threshold=10)))),
            ("count_with_property", criteria(path(atom(aggregation_property="x")))),
            ("count_zero_threshold", criteria(path(atom(threshold=0)))),
            ("count_fractional_threshold", criteria(path(atom(threshold=2.5)))),
            ("sum_zero_threshold", criteria(path(atom(aggregation="sum", aggregation_property="x", threshold=0)))),
            ("min_matches_zero", criteria(path(atom(), min_matches=0))),
            ("min_matches_above_atom_count", criteria(path(atom(), atom("f"), min_matches=3))),
            ("min_matches_fractional", criteria({"atoms": [atom()], "min_matches": 1.5})),
        ]
    )
    def test_rejects_inadmissible_criteria(self, _name: str, data) -> None:
        with pytest.raises(CriteriaValidationError):
            parse_criteria(data)

    def test_parses_full_grammar(self) -> None:
        parsed = parse_criteria(
            criteria(
                path(
                    atom("uploaded_file", threshold=3),
                    atom("purchase", aggregation="sum", aggregation_property="amount", threshold=99.5),
                    atom("viewed", aggregation="distinct", aggregation_property="page", threshold=2),
                    min_matches=2,
                ),
                path(atom("invited_teammate", properties=[{"key": "plan", "value": "pro"}])),
            )
        )
        assert [len(p.atoms) for p in parsed.paths] == [3, 1]
        assert parsed.paths[0].effective_min_matches == 2
        assert parsed.paths[1].effective_min_matches == 1
        assert [(i, a.event) for i, a in parsed.flat_atoms()] == [
            (0, "uploaded_file"),
            (0, "purchase"),
            (0, "viewed"),
            (1, "invited_teammate"),
        ]
        assert parsed.paths[0].atoms[1].threshold == 99.5
        assert parsed.paths[1].atoms[0].properties == ({"key": "plan", "value": "pro"},)


class TestResolve:
    def test_and_path_completes_at_last_atom_completion(self) -> None:
        parsed = parse_criteria(criteria(path(atom("a", threshold=2), atom("b"))))
        resolution = resolve(
            parsed,
            [AtomOutcome(attained=3, completion=ts(30)), AtomOutcome(attained=1, completion=ts(10))],
        )
        assert resolution is not None
        assert resolution.reached_at == ts(30)
        assert resolution.winning_path == 0

    def test_or_paths_complete_at_earliest_satisfied_path(self) -> None:
        parsed = parse_criteria(criteria(path(atom("a")), path(atom("b"))))
        resolution = resolve(
            parsed,
            [AtomOutcome(attained=1, completion=ts(45)), AtomOutcome(attained=1, completion=ts(5))],
        )
        assert resolution is not None
        assert resolution.reached_at == ts(5)
        assert resolution.winning_path == 1

    def test_m_of_n_completes_at_mth_smallest_completion(self) -> None:
        parsed = parse_criteria(criteria(path(atom("a"), atom("b"), atom("c"), min_matches=2)))
        resolution = resolve(
            parsed,
            [
                AtomOutcome(attained=1, completion=ts(40)),
                AtomOutcome(attained=0, completion=None),
                AtomOutcome(attained=1, completion=ts(20)),
            ],
        )
        assert resolution is not None
        assert resolution.reached_at == ts(40)

    def test_unsatisfied_returns_none(self) -> None:
        parsed = parse_criteria(criteria(path(atom("a", threshold=2), atom("b"))))
        assert resolve(parsed, [AtomOutcome(1, ts(1)), AtomOutcome(1, ts(2))]) is None

    def test_missing_completion_fails_toward_late(self) -> None:
        # attained crosses the threshold but no completion time is known: treat as
        # unsatisfied rather than fabricate a reached moment.
        parsed = parse_criteria(criteria(path(atom("a"))))
        assert resolve(parsed, [AtomOutcome(attained=5, completion=None)]) is None

    def test_evidence_carries_aggregate_values_only(self) -> None:
        parsed = parse_criteria(
            criteria(
                path(atom("a", aggregation="sum", aggregation_property="amount", threshold=100)),
                path(atom("b", threshold=2)),
            )
        )
        resolution = resolve(
            parsed,
            [AtomOutcome(attained=120.5, completion=ts(3)), AtomOutcome(attained=1, completion=None)],
        )
        assert resolution is not None
        assert resolution.evidence == {
            "winning_path": 0,
            "paths": [
                {
                    "satisfied": True,
                    "min_matches": 1,
                    "atoms": [
                        {
                            "event": "a",
                            "aggregation": "sum",
                            "aggregation_property": "amount",
                            "threshold": 100.0,
                            "attained": 120.5,
                            "satisfied": True,
                        }
                    ],
                },
                {
                    "satisfied": False,
                    "min_matches": 1,
                    "atoms": [
                        {
                            "event": "b",
                            "aggregation": "count",
                            "aggregation_property": None,
                            "threshold": 2.0,
                            "attained": 1.0,
                            "satisfied": False,
                        }
                    ],
                },
            ],
        }
