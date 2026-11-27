from collections.abc import Callable

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.experiments.backend.facade import testing
from products.experiments.backend.models.experiment import Experiment, ExperimentQuerySet
from products.feature_flags.backend.facade.api import create_flag

ALL_DELETED_STATES: frozenset[bool | None] = frozenset({False, True, None})

Scope = Callable[[ExperimentQuerySet, "TestExperimentLookups"], ExperimentQuerySet]

SCOPES: list[tuple[str, Scope, set[str]]] = [
    ("for_team_of_the_root_team", lambda rows, t: rows.for_team(t.team.id), {"root"}),
    ("for_team_of_an_environment", lambda rows, t: rows.for_team(t.environment.id), {"root"}),
    ("on_exact_team_of_the_root_team", lambda rows, t: rows.on_exact_team(t.team.id), {"root"}),
    ("on_exact_team_of_an_environment", lambda rows, t: rows.on_exact_team(t.environment.id), {"environment"}),
    (
        "on_exact_teams",
        lambda rows, t: rows.on_exact_teams([t.environment.id, t.other_project.id]),
        {"environment", "other_project"},
    ),
    ("in_project", lambda rows, t: rows.in_project(t.team.project_id), {"root", "environment"}),
    (
        "in_organization",
        lambda rows, t: rows.in_organization(t.organization.id),
        {"root", "environment", "other_project"},
    ),
    (
        "on_flags",
        lambda rows, t: rows.on_flags(t.flag_ids("environment", "other_organization")),
        {"environment", "other_organization"},
    ),
]

DELETED_FILTERS: list[tuple[str, Callable[[ExperimentQuerySet], ExperimentQuerySet], frozenset[bool | None]]] = [
    ("live", lambda rows: rows.live(), frozenset({False, None})),
    ("including_deleted", lambda rows: rows.including_deleted(), ALL_DELETED_STATES),
    ("deleted_is_false", lambda rows: rows.deleted_is_false(), frozenset({False})),
]


class TestExperimentLookups(BaseTest):
    environment: Team
    other_project: Team
    ids: dict[tuple[str, bool | None], int]
    flags: dict[tuple[str, bool | None], int]

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.environment = Team.objects.create(
            organization=cls.organization, project=cls.team.project, parent_team=cls.team, name="Environment"
        )
        cls.other_project = Team.objects.create(organization=cls.organization, name="Other project")
        other_organization = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        teams = {
            "root": cls.team,
            # A save moves an experiment to the root team, so the row is moved onto the environment afterwards.
            "environment": cls.team,
            "other_project": cls.other_project,
            "other_organization": other_organization,
        }
        cls.ids = {}
        cls.flags = {}
        for placement, team in teams.items():
            for deleted in ALL_DELETED_STATES:
                flag = create_flag({"key": f"flag-{placement}-{deleted}"}, team=team, user=cls.user)
                cls.flags[placement, deleted] = flag.id
                cls.ids[placement, deleted] = testing.create_experiment(
                    team_id=team.id, feature_flag_id=flag.id, deleted=deleted
                )
        Experiment.objects.filter(
            id__in=[id for (placement, _), id in cls.ids.items() if placement == "environment"]
        ).update(team_id=cls.environment.id)

    def flag_ids(self, *placements: str) -> list[int]:
        return [id for (placement, _), id in self.flags.items() if placement in placements]

    def labels(self, rows: ExperimentQuerySet) -> set[tuple[str, bool | None]]:
        label_of = {id: label for label, id in self.ids.items()}
        return {label_of[id] for id in rows.values_list("id", flat=True)}

    @parameterized.expand(
        [
            (f"{scope_name}_{deleted_name}", scope, placements, deleted_filter, deleted_states)
            for scope_name, scope, placements in SCOPES
            for deleted_name, deleted_filter, deleted_states in DELETED_FILTERS
        ]
    )
    def test_scope_and_deleted_filter(
        self,
        _name: str,
        scope: Scope,
        placements: set[str],
        deleted_filter: Callable[[ExperimentQuerySet], ExperimentQuerySet],
        deleted_states: frozenset[bool | None],
    ) -> None:
        rows = deleted_filter(scope(Experiment.objects.all(), self))

        assert self.labels(rows) == {(placement, deleted) for placement in placements for deleted in deleted_states}

    @parameterized.expand([("objects", ALL_DELETED_STATES), ("live_objects", frozenset({False, None}))])
    def test_managers_resolve_an_environment_to_its_root_team(
        self, manager_name: str, deleted_states: frozenset[bool | None]
    ) -> None:
        rows = getattr(Experiment, manager_name).filter(team_id=self.environment.id)

        assert self.labels(rows) == {("root", deleted) for deleted in deleted_states}
