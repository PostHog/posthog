"""Unit tests for the deltalite write-path rollout flag (is_deltalite_write_enabled).

The flag is the sole control for phase 2 (deltalite performing the real incremental merge); it must
fail closed and pass the schema/team/source_type person properties so it can be targeted per schema.
"""

from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core import deltalite_write


def test_flag_returns_false_when_team_missing():
    with patch("posthog.models.Team") as team_cls:
        team_cls.DoesNotExist = Exception
        team_cls.objects.only.return_value.get.side_effect = team_cls.DoesNotExist
        assert deltalite_write.is_deltalite_write_enabled(1, "abc") is False


def test_flag_returns_false_when_evaluation_raises():
    fake_team = MagicMock(uuid="u", organization_id="o")
    with (
        patch("posthog.models.Team") as team_cls,
        patch.object(deltalite_write.posthoganalytics, "feature_enabled", side_effect=RuntimeError("flags down")),
    ):
        team_cls.objects.only.return_value.get.return_value = fake_team
        assert deltalite_write.is_deltalite_write_enabled(1, "abc") is False


def test_flag_passes_write_key_and_person_properties():
    fake_team = MagicMock(uuid="u", organization_id="o")
    with (
        patch("posthog.models.Team") as team_cls,
        patch.object(deltalite_write.posthoganalytics, "feature_enabled", return_value=True) as fe,
    ):
        team_cls.objects.only.return_value.get.return_value = fake_team
        assert deltalite_write.is_deltalite_write_enabled(2, "sch-123", "stripe") is True
    args, kwargs = fe.call_args
    assert args[0] == deltalite_write.WAREHOUSE_DELTALITE_WRITE_FLAG == "data-warehouse-deltalite-write"
    assert kwargs["person_properties"] == {"schema_id": "sch-123", "team_id": "2", "source_type": "stripe"}
    assert kwargs["send_feature_flag_events"] is False


def test_flag_resolves_source_type_from_schema_when_not_passed():
    # When the caller omits source_type it must be resolved from the schema, so a `source_type = <x>`
    # release condition (e.g. excluding Sentry) can actually match.
    fake_team = MagicMock(uuid="u", organization_id="o")
    fake_schema = MagicMock()
    fake_schema.source.source_type = "postgres"
    with (
        patch("posthog.models.Team") as team_cls,
        patch("products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema") as schema_cls,
        patch.object(deltalite_write.posthoganalytics, "feature_enabled", return_value=True) as fe,
    ):
        team_cls.objects.only.return_value.get.return_value = fake_team
        schema_cls.objects.select_related.return_value.get.return_value = fake_schema
        assert deltalite_write.is_deltalite_write_enabled(1, "sch-9") is True
    assert fe.call_args.kwargs["person_properties"]["source_type"] == "postgres"
