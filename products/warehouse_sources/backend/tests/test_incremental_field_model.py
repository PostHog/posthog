from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.llm.system_one import (
    ChoiceAnswer,
    JsonValue,
    Question,
    RefusalAnswer,
    SystemOneRequestFailed,
    SystemOneResult,
)

from products.warehouse_sources.backend.logic import incremental_field_model
from products.warehouse_sources.backend.logic.incremental_field_model import (
    MODEL_PICK_NOTE,
    recommend_incremental_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    rank_incremental_fields,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

MODULE = "products.warehouse_sources.backend.logic.incremental_field_model"


def _field(name: str, field_type: IncrementalFieldType = IncrementalFieldType.Timestamp) -> IncrementalField:
    return {"label": name, "type": field_type, "field": name, "field_type": field_type, "nullable": False}


def _schema(name: str, *fields: IncrementalField) -> SourceSchema:
    return SourceSchema(
        name=name,
        supports_incremental=True,
        supports_append=True,
        incremental_fields=rank_incremental_fields(list(fields)),
    )


def _open_schema(name: str = "orders") -> SourceSchema:
    # No column name says "updated", so the rules can only guess `created_at`.
    return _schema(
        name, _field("created_at"), _field("fecha_actualizacion"), _field("id", IncrementalFieldType.Integer)
    )


class _FakeClient:
    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[tuple[JsonValue, Mapping[str, Question]]] = []

    def decide(self, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        self.calls.append((state, questions))
        if self.error is not None:
            raise self.error
        return SystemOneResult(model="jeeves-0.1", answers=dict.fromkeys(questions, self.answer), input_tokens=10)


def _pick(option: str, confidence: float = 0.9) -> ChoiceAnswer:
    return ChoiceAnswer(choice=option, confidence=confidence, probabilities={option: confidence})


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestRecommendIncrementalFields(SimpleTestCase):
    def setUp(self) -> None:
        incremental_field_model.cache.clear()
        self.team: Any = SimpleNamespace(
            pk=7, organization_id="org-1", organization=SimpleNamespace(is_ai_data_processing_approved=True)
        )

    def _run(
        self,
        schemas: list[SourceSchema],
        client: _FakeClient,
        *,
        flag: bool = True,
        configured: bool = True,
    ) -> None:
        with (
            patch(f"{MODULE}.build_system_one_client", return_value=client),
            patch(f"{MODULE}.system_one_configured", return_value=configured),
            patch(f"{MODULE}.feature_enabled_or_false", return_value=flag),
        ):
            recommend_incremental_fields(schemas, team=self.team)

    def test_confident_pick_becomes_the_recommended_field(self) -> None:
        schema = _open_schema()
        client = _FakeClient(_pick("c2"))

        self._run([schema], client)

        assert [(f["field"], f["recommended"]) for f in schema.incremental_fields] == [
            ("fecha_actualizacion", True),
            ("created_at", False),
            ("id", False),
        ]
        assert schema.incremental_fields[0]["notes"][0] == MODEL_PICK_NOTE
        state, questions = client.calls[0]
        assert list(questions) == ["t0"]
        assert state == {
            "tables": {
                "t0": {
                    "table": "orders",
                    "columns": [
                        {"option": "c0", "name": "created_at", "type": "timestamp", "indexed": True, "nullable": False},
                        {"option": "c1", "name": "id", "type": "integer", "indexed": True, "nullable": False},
                        {
                            "option": "c2",
                            "name": "fecha_actualizacion",
                            "type": "timestamp",
                            "indexed": True,
                            "nullable": False,
                        },
                    ],
                }
            }
        }

    @parameterized.expand(
        [
            ("low_confidence", _FakeClient(_pick("c1", confidence=0.4))),
            ("refusal", _FakeClient(RefusalAnswer())),
            ("option_out_of_range", _FakeClient(_pick("c9"))),
            ("gateway_error", _FakeClient(error=SystemOneRequestFailed("HTTP 529", status_code=529))),
            ("unexpected_error", _FakeClient(error=ValueError("'t0' has more than 16 options"))),
        ]
    )
    def test_unusable_answer_keeps_the_rule_based_order(self, _name: str, client: _FakeClient) -> None:
        schema = _open_schema()
        before = [dict(field) for field in schema.incremental_fields]

        self._run([schema], client)

        assert schema.incremental_fields == before
        assert len(client.calls) == 1

    @parameterized.expand(
        [
            ("update_column_found", _schema("orders", _field("created_at"), _field("updated_at")), {}),
            ("single_candidate", _schema("orders", _field("created_at")), {}),
            ("flag_off", _open_schema(), {"flag": False}),
            ("gateway_not_configured", _open_schema(), {"configured": False}),
        ]
    )
    def test_model_is_not_asked(self, _name: str, schema: SourceSchema, gates: dict[str, bool]) -> None:
        client = _FakeClient(_pick("c1"))

        self._run([schema], client, **gates)

        assert client.calls == []

    def test_model_is_not_asked_without_ai_data_processing_consent(self) -> None:
        self.team.organization.is_ai_data_processing_approved = False
        client = _FakeClient(_pick("c1"))

        self._run([_open_schema()], client)

        assert client.calls == []

    def test_cached_answer_skips_the_model(self) -> None:
        first = _FakeClient(_pick("c2"))
        self._run([_open_schema()], first)
        second = _FakeClient(_pick("c2"))
        schema = _open_schema()

        self._run([schema], second)

        assert second.calls == []
        assert schema.incremental_fields[0]["field"] == "fecha_actualizacion"

    def test_many_open_tables_split_into_requests_the_gateway_accepts(self) -> None:
        schemas = [_open_schema(f"table_{n}") for n in range(40)]
        client = _FakeClient(_pick("c2"))

        self._run(schemas, client)

        assert sorted(len(questions) for _, questions in client.calls) == [8, 32]
        assert all(schema.incremental_fields[0]["field"] == "fecha_actualizacion" for schema in schemas)

    def test_synthetic_xmin_is_never_offered(self) -> None:
        schema = _open_schema()
        schema.incremental_fields.append(
            {"label": "xmin", "type": IncrementalFieldType.XID, "field": "xmin", "field_type": IncrementalFieldType.XID}
        )
        client = _FakeClient(_pick("c1"))

        self._run([schema], client)

        state, _ = client.calls[0]
        assert "xmin" not in str(state)
        assert schema.incremental_fields[-1]["field"] == "xmin"
