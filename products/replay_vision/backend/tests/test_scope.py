from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.schema import RecordingsQuery

from products.replay_vision.backend import observation_ranks
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    ScannerDisabledReason,
    ScannerModel,
    ScannerType,
)
from products.replay_vision.backend.scanner_access import (
    can_read_observation,
    can_read_targeted_experiment,
    snapshot_experiment_scope_q,
)
from products.replay_vision.backend.scope import experiment_id_of, scope_for
from products.replay_vision.backend.scope.load import EXPERIMENT_ID_SNAPSHOT_STORES, settings_of, snapshot_experiment_id
from products.replay_vision.backend.temporal.snapshots import ScannerSnapshot


def _make_scanner(team, **overrides) -> ReplayScanner:
    defaults: dict[str, Any] = {
        "team": team,
        "name": "scope-scanner",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "test"},
        "model": ScannerModel.GEMINI_3_8_FLASH,
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


class TestScopeResolution(BaseTest):
    @parameterized.expand(
        [
            (
                "scope column wins over both older stores",
                {
                    "scope": {"kind": "experiment", "experiment_id": 7},
                    "scanner_type": ScannerType.EXPERIMENT,
                    "scanner_config": {"experiment_id": 1},
                    "experiment_targeting": {"experiment_id": 2},
                },
                7,
            ),
            (
                "native type falls back to scanner_config",
                {"scanner_type": ScannerType.EXPERIMENT, "scanner_config": {"experiment_id": 11}},
                11,
            ),
            (
                "other types fall back to experiment_targeting",
                {"scanner_type": ScannerType.MONITOR, "experiment_targeting": {"experiment_id": 12}},
                12,
            ),
            (
                "native type ignores experiment_targeting",
                {
                    "scanner_type": ScannerType.EXPERIMENT,
                    "scanner_config": {},
                    "experiment_targeting": {"experiment_id": 13},
                },
                None,
            ),
            ("no store set reads as no scope", {"scanner_type": ScannerType.MONITOR}, None),
        ]
    )
    def test_resolution_order(self, _name: str, fields: dict[str, Any], expected_id: int | None) -> None:
        # Unsaved, so the dual write on save does not re-derive `scope` from the older stores
        # before the read under test.
        scanner = ReplayScanner(team=self.team, name="scope-scanner", model=ScannerModel.GEMINI_3_8_FLASH, **fields)

        scope = scope_for(scanner)

        if expected_id is None:
            self.assertIsNone(scope)
        else:
            assert scope is not None
            self.assertEqual(scope.settings.experiment_id, expected_id)

    def test_legacy_singular_variant_becomes_a_one_item_list(self) -> None:
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.MONITOR,
            experiment_targeting={"experiment_id": 5, "variant": "control"},
        )

        scope = scope_for(scanner)

        assert scope is not None
        self.assertEqual(scope.settings.variants, ["control"])

    def test_a_malformed_scope_reads_as_no_scope(self) -> None:
        scanner = _make_scanner(self.team, scope={"kind": "experiment", "experiment_id": "not-an-int"})

        self.assertIsNone(scope_for(scanner))

    def test_an_unknown_kind_reads_as_no_scope(self) -> None:
        scanner = _make_scanner(self.team, scope={"kind": "funnel", "steps": []})

        self.assertIsNone(scope_for(scanner))

    def test_scope_narrows_a_recordings_query_to_the_exposed_population(self) -> None:
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"experiment_id": 9, "variants": ["control", "test"]},
        )
        scope = scope_for(scanner)
        assert scope is not None

        narrowed = scope.recordings_filter(RecordingsQuery())

        assert narrowed.experiment_exposure is not None
        self.assertEqual(narrowed.experiment_exposure.experiment_id, 9)
        self.assertEqual(narrowed.experiment_exposure.variants, ["control", "test"])

    def test_reads_a_snapshot_the_same_way_as_a_scanner(self) -> None:
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"experiment_id": 21, "variants": ["a"]},
        )
        snapshot = ScannerSnapshot.from_scanner(scanner)

        self.assertEqual(experiment_id_of(snapshot), 21)
        self.assertEqual(experiment_id_of(scanner), 21)

    def test_access_check_gates_an_experiment_held_only_in_scope(self) -> None:
        # `experiment_scope` reads only the two older stores, so a scanner whose experiment lives
        # in `scope` alone reads as untargeted there. The gate has to see the column, or it admits
        # a caller who cannot view the experiment.
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.MONITOR,
            scope={"kind": "experiment", "experiment_id": 31},
        )
        self.assertIsNone(scanner.experiment_scope())

        with patch(
            "products.replay_vision.backend.scanner_access.is_experiment_accessible",
            return_value=False,
        ) as accessible:
            self.assertFalse(can_read_targeted_experiment(Mock(), self.team.id, scanner))

        self.assertEqual(accessible.call_args.args[2], 31)


class TestSnapshotAccessGate(BaseTest):
    def test_a_scope_only_snapshot_is_not_readable_by_a_denied_caller(self) -> None:
        # The observation gate reads the experiment off the frozen snapshot. Reading only the two
        # older stores makes a scope-only snapshot look like it names no experiment, and the
        # "names none, so unrestricted" branch then hands its rows to a caller denied that
        # experiment. The pipeline change is what makes those rows exist: before it, a scope-only
        # scanner produced no variant labels at all.
        observation = Mock()
        observation.scanner_snapshot = {"scope": {"kind": "experiment", "experiment_id": 77}}

        with patch(
            "products.replay_vision.backend.scanner_access.accessible_experiment_ids",
            return_value=set(),
        ):
            self.assertFalse(can_read_observation(Mock(), self.team.id, observation))

        # Granting that same experiment admits the caller, which is what shows the gate read the
        # id out of `scope` rather than refusing every snapshot it cannot parse.
        with patch(
            "products.replay_vision.backend.scanner_access.accessible_experiment_ids",
            return_value={77},
        ):
            self.assertTrue(can_read_observation(Mock(), self.team.id, observation))

    def test_a_snapshot_naming_no_experiment_anywhere_stays_readable(self) -> None:
        # Every observation predating the scope column has none of the three stores set, and must
        # keep reading as unrestricted.
        observation = Mock()
        observation.scanner_snapshot = {"scanner_config": {"prompt": "p"}}

        self.assertTrue(can_read_observation(Mock(), self.team.id, observation))

    @parameterized.expand([(store,) for store in EXPERIMENT_ID_SNAPSHOT_STORES])
    def test_every_store_is_read_by_every_snapshot_reader(self, store: str) -> None:
        """Each reader of a frozen snapshot has to know every store an experiment can live in.

        Three readers in three languages ask this question, so none can share a function. This is
        what stops a fourth from hardcoding a subset: a store added to the shared list fails here
        until every reader covers it. A reader that misses one reads a snapshot held only in that
        store as naming no experiment, which the rank filters and the access gates both treat as
        readable by anyone.
        """
        snapshot = {store: {"experiment_id": 404}}

        self.assertEqual(snapshot_experiment_id(snapshot), 404, "snapshot_experiment_id misses this store")
        self.assertIn(
            f"scanner_snapshot__{store}__experiment_id",
            str(snapshot_experiment_scope_q(unrestricted=True, experiment_ids=[5])),
            "the observation access filter misses this store",
        )
        self.assertIn(
            f"{{{store},experiment_id}}",
            observation_ranks._EXPERIMENT_SQL,
            "the rank row's experiment column misses this store",
        )

    def test_a_snapshot_naming_nothing_reads_as_no_experiment(self) -> None:
        self.assertIsNone(snapshot_experiment_id({"scanner_config": {"prompt": "p"}}))
        self.assertIsNone(snapshot_experiment_id(None))


class TestScopesTheMirrorWroteBeforeBalance(BaseTest):
    """Scopes the mirror wrote before `balance` reached the settings model carry neither it nor
    `start_on_launch`, and `stored_scope` prefers the stored blob over re-deriving one."""

    def test_a_stale_mirrored_scope_still_samples_proportionally(self) -> None:
        # The regression: reading the blob as it stands gives `balance` its default of True, so a
        # scanner whose config turned balancing off starts sampling evenly on its next sweep.
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={
                "prompt": "p",
                "experiment_id": 9,
                "variants": ["control", "test"],
                "balance_variants": False,
            },
        )
        # Written as the mirror wrote it before `balance` existed: derived, but missing the key.
        ReplayScanner.all_origins.filter(pk=scanner.pk).update(
            scope={"kind": "experiment", "experiment_id": 9, "variants": ["control", "test"]}
        )
        scanner.refresh_from_db()

        settings = settings_of(scanner)
        assert settings is not None
        self.assertFalse(settings.balance)

    def test_a_scope_that_already_carries_balance_is_left_alone(self) -> None:
        # Every row saved once this ships carries the key, so the fill is skipped without deriving
        # anything. That is the common path after the migration, and the one that costs nothing.
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"prompt": "p", "experiment_id": 9, "variants": ["control", "test"]},
        )
        ReplayScanner.all_origins.filter(pk=scanner.pk).update(
            scope={
                "kind": "experiment",
                "experiment_id": 9,
                "variants": ["control", "test"],
                "balance": False,
                "start_on_launch": False,
            }
        )
        scanner.refresh_from_db()

        settings = settings_of(scanner)
        assert settings is not None
        self.assertFalse(settings.balance)

    def test_a_scope_set_by_hand_keeps_its_own_default(self) -> None:
        # Only a blob this row's own mirror owns is filled. A scope that disagrees with the older
        # store was set deliberately, and a `balance` left at its default there means True.
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={
                "prompt": "p",
                "experiment_id": 9,
                "variants": ["control", "test"],
                "balance_variants": False,
            },
        )
        ReplayScanner.all_origins.filter(pk=scanner.pk).update(
            scope={"kind": "experiment", "experiment_id": 9, "variants": ["control"]}
        )
        scanner.refresh_from_db()

        settings = settings_of(scanner)
        assert settings is not None
        self.assertTrue(settings.balance)


class TestScopeDualWrite(BaseTest):
    def test_saving_a_legacy_scanner_mirrors_its_experiment_into_scope(self) -> None:
        scanner = _make_scanner(self.team, scanner_type=ScannerType.MONITOR, experiment_targeting={"experiment_id": 31})
        scanner.refresh_from_db()

        self.assertEqual(scanner.scope, {"kind": "experiment", "experiment_id": 31})

    def test_saving_a_native_experiment_scanner_mirrors_its_config_into_scope(self) -> None:
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"experiment_id": 32, "variants": ["control"]},
        )
        scanner.refresh_from_db()

        self.assertEqual(scanner.scope, {"kind": "experiment", "experiment_id": 32, "variants": ["control"]})

    def test_a_native_scanner_that_samples_proportionally_carries_that_into_scope(self) -> None:
        # The sampler reads `balance` from the scope, so a config that turned balancing off has to
        # survive the derivation. Losing it would silently switch the scanner to balanced rates.
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"experiment_id": 32, "variants": ["control"], "balance_variants": False},
        )
        scanner.refresh_from_db()

        self.assertEqual(
            scanner.scope,
            {"kind": "experiment", "experiment_id": 32, "variants": ["control"], "balance": False},
        )

    def test_a_default_balance_stays_out_of_the_mirrored_scope(self) -> None:
        # The mirror decides whether it owns a row's scope by comparing the stored blob against a
        # fresh derivation. A defaulted key written into the blob would move that shape under every
        # row already mirrored, and the mirror would read them all as scopes set by hand.
        scanner = _make_scanner(
            self.team,
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"experiment_id": 32, "variants": ["control"], "balance_variants": True},
        )
        scanner.refresh_from_db()

        self.assertEqual(scanner.scope, {"kind": "experiment", "experiment_id": 32, "variants": ["control"]})

    def test_an_unscoped_scanner_keeps_a_null_scope(self) -> None:
        scanner = _make_scanner(self.team, scanner_type=ScannerType.MONITOR)
        scanner.refresh_from_db()

        self.assertIsNone(scanner.scope)

    def test_retargeting_moves_the_mirrored_scope(self) -> None:
        scanner = _make_scanner(self.team, scanner_type=ScannerType.MONITOR, experiment_targeting={"experiment_id": 41})

        scanner.experiment_targeting = {"experiment_id": 42}
        scanner.save()
        scanner.refresh_from_db()

        self.assertEqual(scanner.scope, {"kind": "experiment", "experiment_id": 42})

    def test_clearing_targeting_clears_the_mirrored_scope(self) -> None:
        scanner = _make_scanner(self.team, scanner_type=ScannerType.MONITOR, experiment_targeting={"experiment_id": 43})

        scanner.experiment_targeting = None
        scanner.save()
        scanner.refresh_from_db()

        self.assertIsNone(scanner.scope)

    def test_retargeting_bumps_the_scanner_version(self) -> None:
        scanner = _make_scanner(self.team, scanner_type=ScannerType.MONITOR, experiment_targeting={"experiment_id": 44})
        before = scanner.scanner_version

        scanner.experiment_targeting = {"experiment_id": 45}
        scanner.save()
        scanner.refresh_from_db()

        self.assertEqual(scanner.scanner_version, before + 1)

    def test_a_partial_save_of_other_fields_keeps_the_persisted_scope(self) -> None:
        # A sweep holds the scanner from before a retarget. Its `turn_off` persists only `enabled`,
        # so the mirror must leave `scope` alone. Deriving it from this stale instance would
        # authorize the previous experiment while the recording query targets the new one.
        scanner = _make_scanner(
            self.team, scanner_type=ScannerType.MONITOR, experiment_targeting={"experiment_id": 111}
        )
        stale = ReplayScanner.objects.get(pk=scanner.pk)

        retargeted = ReplayScanner.objects.get(pk=scanner.pk)
        retargeted.experiment_targeting = {"experiment_id": 222}
        retargeted.save()

        stale.turn_off(ScannerDisabledReason.FREE_CREDITS_USED)

        scanner.refresh_from_db()
        self.assertEqual(scanner.experiment_targeting, {"experiment_id": 222})
        self.assertEqual(scanner.scope, {"kind": "experiment", "experiment_id": 222})
        self.assertEqual(experiment_id_of(scanner), 222)

    def test_mirroring_on_an_update_that_names_its_fields(self) -> None:
        scanner = _make_scanner(self.team, scanner_type=ScannerType.MONITOR)
        ReplayScanner.objects.filter(pk=scanner.pk).update(scope=None)
        scanner.refresh_from_db()

        scanner.experiment_targeting = {"experiment_id": 34}
        scanner.save(update_fields=["experiment_targeting"])
        scanner.refresh_from_db()

        self.assertEqual(scanner.scope, {"kind": "experiment", "experiment_id": 34})
