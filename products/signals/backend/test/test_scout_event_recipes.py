from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import RFC_4122, UUID, uuid5

from unittest import TestCase
from unittest.mock import patch

from pydantic import ValidationError

from products.posthog_ai.eval_harness.environment.schema import EVENT_TABLE, EnvironmentEvent
from products.signals.backend.scout_harness.eval_environment import recipes
from products.signals.backend.scout_harness.eval_environment.recipes import EventGroupRecipe, EventRecipe


class TestEventRecipes(TestCase):
    def test_generated_uuidv7_is_deterministic_and_preserves_source_time_and_observed_rows(self) -> None:
        cutoff = datetime(2030, 1, 2, tzinfo=UTC)
        timestamp = cutoff - timedelta(minutes=1, microseconds=876544)
        sample = EnvironmentEvent(
            uuid=UUID("00000000-0000-4000-8000-000000000001"),
            event="example_call",
            timestamp=cutoff - timedelta(hours=1),
            created_at=cutoff - timedelta(hours=1),
            distinct_id="observed-example",
            properties={"organization": "example-org", "observed": True},
        )
        recipe = EventRecipe(
            namespace=UUID("00000000-0000-4000-8000-000000000002"),
            source_cutoff=cutoff,
            generated_uuid_version=7,
            groups=[
                EventGroupRecipe(
                    key="example",
                    event="example_call",
                    count=3,
                    start=cutoff - timedelta(hours=2),
                    end=cutoff,
                    organization_properties=["organization"],
                    organization_frequencies={"example-org": 3},
                    samples=[sample],
                    generated_timestamps=[timestamp, timestamp],
                )
            ],
        )
        events = recipe.events()
        assert events == recipe.events()
        assert sample in events
        generated = [event for event in events if event.uuid != sample.uuid]
        assert len({event.uuid for event in generated}) == 2
        expected_milliseconds = int(timestamp.timestamp() * 1000)
        for event in generated:
            assert event.uuid.version == 7
            assert event.uuid.variant == RFC_4122
            assert event.uuid.int >> 80 == expected_milliseconds
            assert event.timestamp == timestamp
        legacy = EventRecipe.model_validate(recipe.model_dump(exclude={"generated_uuid_version"}))
        assert {event.uuid for event in legacy.events() if event.uuid != sample.uuid} == {
            uuid5(recipe.namespace, "example:0"),
            uuid5(recipe.namespace, "example:1"),
        }

    def test_write_events_publishes_only_a_complete_file(self) -> None:
        cutoff = datetime(2030, 1, 2, tzinfo=UTC)
        recipe = EventRecipe(
            namespace=UUID("00000000-0000-4000-8000-000000000002"),
            source_cutoff=cutoff,
            groups=[
                EventGroupRecipe(
                    key="example",
                    event="example_call",
                    count=2,
                    start=cutoff - timedelta(hours=2),
                    end=cutoff,
                    organization_properties=["organization"],
                    organization_frequencies={"example-org": 2},
                    generated_timestamps=[cutoff - timedelta(hours=1)] * 2,
                    properties={"organization": "example-org"},
                )
            ],
        )
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "events.parquet"
            with (
                patch.object(recipes.EVENT_TABLE, "write", side_effect=OSError("disk full")),
                self.assertRaises(OSError),
            ):
                recipe.write_events(output)
            assert list(Path(temporary).iterdir()) == []

            recipe.write_events(output)
            assert list(EVENT_TABLE.read(output)) == recipe.events()
            assert [path.name for path in Path(temporary).iterdir()] == ["events.parquet"]
            with self.assertRaises(FileExistsError):
                recipe.write_events(output)

    def test_generated_uuidv7_rejects_timestamps_before_the_unix_epoch(self) -> None:
        cutoff = datetime(1970, 1, 1, tzinfo=UTC)
        recipe = EventRecipe(
            namespace=UUID("00000000-0000-4000-8000-000000000002"),
            source_cutoff=cutoff,
            generated_uuid_version=7,
            groups=[
                EventGroupRecipe(
                    key="example",
                    event="example_call",
                    count=1,
                    start=cutoff - timedelta(days=1),
                    end=cutoff,
                    organization_properties=["organization"],
                    organization_frequencies={"example-org": 1},
                    generated_timestamps=[cutoff - timedelta(milliseconds=1)],
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "unsigned 48-bit"):
            recipe.events()

    def test_preserves_observed_sample_and_rejects_inconsistent_recipes(self) -> None:
        cutoff = datetime(2030, 1, 2, tzinfo=UTC)
        sample = EnvironmentEvent(
            uuid=UUID("00000000-0000-4000-8000-000000000001"),
            event="example_call",
            timestamp=cutoff - timedelta(hours=1),
            created_at=cutoff - timedelta(hours=1),
            distinct_id="observed-example",
            properties={"organization": "example-org", "extra": "observed"},
        )
        group = {
            "key": "example",
            "event": "example_call",
            "count": 3,
            "start": cutoff - timedelta(hours=2),
            "end": cutoff,
            "organization_properties": ["organization"],
            "organization_frequencies": {"example-org": 2, "another-org": 1},
            "samples": [sample],
            "generated_timestamps": [cutoff - timedelta(minutes=20), cutoff - timedelta(minutes=10)],
        }
        arguments = {"namespace": UUID("00000000-0000-4000-8000-000000000002"), "source_cutoff": cutoff}
        recipe = EventRecipe(**arguments, groups=[group])
        events = recipe.events()
        self.assertEqual(events, recipe.events())
        self.assertIn(sample, events)
        generated_id = next(event.uuid for event in events if event.uuid != sample.uuid)
        omitted = recipe.model_copy(update={"generated_property_omissions": {"organization": [generated_id]}})
        omitted_events = omitted.events()
        self.assertNotIn(
            "organization", next(event for event in omitted_events if event.uuid == generated_id).properties
        )
        self.assertIn(sample, omitted_events)
        for identifier in (sample.uuid, UUID("00000000-0000-4000-8000-000000000099")):
            invalid = recipe.model_copy(update={"generated_property_omissions": {"organization": [identifier]}})
            with self.assertRaisesRegex(ValueError, "only to generated"):
                invalid.events()
        self.assertEqual(
            sorted(event.properties["organization"] for event in events), ["another-org", "example-org", "example-org"]
        )
        for changes in (
            {"organization_frequencies": {"another-org": 3}},
            {"generated_timestamps": [cutoff, cutoff - timedelta(minutes=10)]},
            {"end": cutoff + timedelta(seconds=1)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                EventRecipe(**arguments, groups=[{**group, **changes}])
