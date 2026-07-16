from posthog.schema import SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TypeformSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.typeform.source import TypeformSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTypeformSource:
    def setup_method(self):
        self.source = TypeformSource()
        self.team_id = 123

    def _response_types_field(self) -> SourceFieldSelectConfig:
        field = next(f for f in self.source.get_source_config.fields if f.name == "response_types")
        assert isinstance(field, SourceFieldSelectConfig)
        return field

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.TYPEFORM

    def test_response_types_field_defaults_to_completed(self):
        field = self._response_types_field()
        assert field.defaultValue == "completed"
        assert [option.value for option in field.options] == ["completed", "completed,partial,started"]

    def test_response_types_field_warns_about_full_refresh(self):
        field = self._response_types_field()
        assert field.caption is not None
        assert "full refresh" in field.caption.lower()

    def test_get_schemas_completed_only_uses_submitted_at(self):
        config = TypeformSourceConfig(auth_token="token", response_types="completed")
        responses = next(s for s in self.source.get_schemas(config, self.team_id) if s.name == "responses")
        assert [f["field"] for f in responses.incremental_fields] == ["submitted_at"]

    def test_get_schemas_with_partials_is_full_refresh(self):
        config = TypeformSourceConfig(auth_token="token", response_types="completed,partial,started")
        responses = next(s for s in self.source.get_schemas(config, self.team_id) if s.name == "responses")
        # Partial/started responses have no submitted_at and share no cursor with completed ones,
        # so the all-responses mode is full-refresh only.
        assert responses.supports_incremental is False
        assert responses.incremental_fields == []

    def test_get_schemas_forms_unaffected_by_response_types(self):
        config = TypeformSourceConfig(auth_token="token", response_types="completed,partial,started")
        forms = next(s for s in self.source.get_schemas(config, self.team_id) if s.name == "forms")
        assert [f["field"] for f in forms.incremental_fields] == ["last_updated_at"]
