import importlib.util
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest, TestMigrations

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.scope.load import derive_scope

_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "0158_backfill_replayscanner_scope.py"


def _migration():
    """The migration module, loaded by path because its name starts with a digit."""
    spec = importlib.util.spec_from_file_location("backfill_0158", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MODEL = "gemini-3.8-flash"


class TestBackfillReplayScannerScope(TestMigrations):
    app = "replay_vision"
    migrate_from = "0157_drop_replayscanner_sampling_mode_column"
    migrate_to = "0158_backfill_replayscanner_scope"

    def setUpBeforeMigration(self, apps: Any) -> None:
        ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")

        created = 0

        def scanner(**fields):
            nonlocal created
            created += 1
            # Named apart because a team may hold one configured scanner per name.
            defaults = {
                "team_id": self.team.id,
                "name": f"s{created}",
                "model": _MODEL,
                "scanner_config": {"prompt": "p"},
            }
            return ReplayScanner.objects.create(**{**defaults, **fields}).id

        self.native = scanner(
            scanner_type="experiment",
            scanner_config={"prompt": "p", "length": "medium", "experiment_id": 11, "variants": ["control", "test"]},
        )
        self.native_proportional = scanner(
            scanner_type="experiment",
            scanner_config={"prompt": "p", "experiment_id": 12, "variants": ["control"], "balance_variants": False},
        )
        self.native_every_variant = scanner(
            scanner_type="experiment",
            scanner_config={"prompt": "p", "experiment_id": 13},
        )
        self.native_waiting = scanner(
            scanner_type="experiment",
            scanner_config={"prompt": "p", "experiment_id": 14, "start_on_launch": True},
            enabled=False,
        )
        self.native_without_experiment = scanner(
            scanner_type="experiment",
            scanner_config={"prompt": "p"},
        )
        self.legacy_single = scanner(
            scanner_type="summarizer",
            experiment_targeting={"experiment_id": 21, "variant": "test"},
        )
        self.legacy_several = scanner(
            scanner_type="classifier",
            scanner_config={"prompt": "p", "tags": ["a"]},
            experiment_targeting={"experiment_id": 22, "variants": ["control", "test"]},
        )
        self.unscoped = scanner(scanner_type="monitor")
        self.already_scoped = scanner(
            scanner_type="summarizer",
            experiment_targeting={"experiment_id": 31},
            scope={"kind": "experiment", "experiment_id": 31, "variants": ["control"]},
        )

    def test_a_native_scanner_keeps_its_type_and_config(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        row = ReplayScanner.objects.get(id=self.native)

        assert row.scanner_type == "experiment"
        assert row.scanner_config == {
            "prompt": "p",
            "length": "medium",
            "experiment_id": 11,
            "variants": ["control", "test"],
        }
        assert row.scope["experiment_id"] == 11
        assert row.scope["variants"] == ["control", "test"]

    def test_a_scanner_that_samples_proportionally_carries_its_balance(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        row = ReplayScanner.objects.get(id=self.native_proportional)

        assert row.scope["balance"] is False
        assert row.scanner_config["balance_variants"] is False

    def test_a_default_balance_stays_out_of_the_backfilled_scope(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        row = ReplayScanner.objects.get(id=self.native)

        assert "balance" not in row.scope
        assert "start_on_launch" not in row.scope

    def test_a_scanner_waiting_for_launch_carries_its_marker(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        row = ReplayScanner.objects.get(id=self.native_waiting)

        assert row.scope["start_on_launch"] is True
        assert row.scanner_config["start_on_launch"] is True

    def test_watching_every_variant_stays_unnarrowed(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        row = ReplayScanner.objects.get(id=self.native_every_variant)

        assert row.scope["experiment_id"] == 13
        assert "variants" not in row.scope

    def test_a_legacy_singular_variant_becomes_a_one_item_list(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        row = ReplayScanner.objects.get(id=self.legacy_single)

        assert row.scope["experiment_id"] == 21
        assert row.scope["variants"] == ["test"]
        assert row.scanner_type == "summarizer"
        assert row.experiment_targeting == {"experiment_id": 21, "variant": "test"}

    def test_a_legacy_column_scanner_keeps_its_column(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        row = ReplayScanner.objects.get(id=self.legacy_several)

        assert row.scanner_type == "classifier"
        assert row.scope["variants"] == ["control", "test"]
        assert row.experiment_targeting["variants"] == ["control", "test"]

    def test_a_scanner_watching_no_experiment_is_left_alone(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        unscoped = ReplayScanner.objects.get(id=self.unscoped)
        without_experiment = ReplayScanner.objects.get(id=self.native_without_experiment)

        assert unscoped.scope is None
        assert without_experiment.scope is None
        assert without_experiment.scanner_type == "experiment"

    def test_an_existing_scope_is_left_as_it_is(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        row = ReplayScanner.objects.get(id=self.already_scoped)

        assert row.scope == {"kind": "experiment", "experiment_id": 31, "variants": ["control"]}
        assert "backfilled_at" not in row.scope

    def test_a_backfilled_scope_carries_no_provenance_key(self) -> None:
        # The mirror decides whether it owns a row's scope by comparing the stored blob against a
        # fresh derivation. A provenance key fails that comparison, and the save that clears a row's
        # `experiment_targeting` would then leave the scope naming the removed experiment in place.
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        backfilled = [
            self.native,
            self.native_proportional,
            self.native_every_variant,
            self.native_waiting,
            self.legacy_single,
            self.legacy_several,
        ]

        for scanner_id in backfilled:
            scope = ReplayScanner.objects.get(id=scanner_id).scope
            assert set(scope) <= {"kind", "experiment_id", "variants", "balance", "start_on_launch"}, scope


class TestBackfillAgreesWithTheMirror(BaseTest):
    """The backfill must derive exactly what `ReplayScanner.save()`'s mirror derives.

    The mirror decides whether it owns a row's scope by comparing the stored blob against a fresh
    derivation. A backfilled scope that differs by one key reads as hand-set, and the mirror then
    stops following the row's legacy stores.
    """

    # Every config and targeting shape the backfill can meet. Parity has to hold for all of them:
    # one key of difference and the mirror stops reading a backfilled row as its own.
    _CONFIGS = [
        {"prompt": "p", "experiment_id": 77, "variants": ["control", "test"]},
        {"prompt": "p", "experiment_id": 77},
        {"prompt": "p", "experiment_id": 77, "variants": []},
        {"prompt": "p", "experiment_id": 77, "variants": None},
        {"prompt": "p", "experiment_id": 77, "balance_variants": False},
        {"prompt": "p", "experiment_id": 77, "balance_variants": True},
        {"prompt": "p", "experiment_id": 77, "start_on_launch": True},
        {"prompt": "p", "experiment_id": 77, "start_on_launch": False},
        {
            "prompt": "p",
            "experiment_id": 77,
            "variants": ["control"],
            "balance_variants": False,
            "start_on_launch": True,
        },
        {"prompt": "p"},
        {"prompt": "p", "experiment_id": 0},
        {"prompt": "p", "experiment_id": None},
        {"prompt": "p", "experiment_id": True},
    ]

    def test_every_native_config_shape_derives_the_same_scope_either_way(self) -> None:
        for config in self._CONFIGS:
            scanner = ReplayScanner(
                team_id=self.team.id,
                name="agreement",
                scanner_type=ScannerType.EXPERIMENT,
                scanner_config=config,
                model=ScannerModel.GEMINI_3_8_FLASH,
            )

            assert _migration()._scope_from_native_config(config) == derive_scope(scanner), config

    def test_a_native_config_derives_the_same_scope_either_way(self) -> None:
        config = {
            "prompt": "p",
            "experiment_id": 77,
            "variants": ["control", "test"],
            "balance_variants": False,
            "start_on_launch": True,
        }
        scanner = ReplayScanner(
            team_id=self.team.id,
            name="agreement",
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config=config,
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

        assert _migration()._scope_from_native_config(config) == derive_scope(scanner)

    def test_a_backfilled_scope_still_follows_a_cleared_targeting(self) -> None:
        # The mirror must keep reading a backfilled row as its own. If it does not, the one save
        # that clears `experiment_targeting` leaves the scope naming the removed experiment, and
        # the scanner keeps sweeping that experiment's sessions while every surface shows it
        # untargeted.
        scanner = ReplayScanner.objects.create(
            team_id=self.team.id,
            name="cleared",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_8_FLASH,
            experiment_targeting={"experiment_id": 43},
        )
        backfilled = _migration()._scope_from_targeting({"experiment_id": 43})
        ReplayScanner.objects.filter(pk=scanner.pk).update(scope=backfilled)
        scanner.refresh_from_db()

        scanner.experiment_targeting = None
        scanner.save()
        scanner.refresh_from_db()

        assert scanner.scope is None
