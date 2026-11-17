import asyncio
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock, patch

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
from posthog.llm.system_one_client import GatewaySystemOneClient
from posthog.redis import TEST_clear_clients, get_client
from posthog.token_bucket import TEST_reset_scripts, consume

from products.warehouse_sources.backend.logic import incremental_field_model
from products.warehouse_sources.backend.logic.incremental_field_model import (
    MODEL_PICK_NOTE,
    SYNC_FORM_PATH,
    WIZARD_PATH,
    fits_one_call,
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
    def __init__(self, answer: Any = None, error: Exception | None = None, hang: bool = False) -> None:
        self.answer = answer
        self.error = error
        self.hang = hang
        self.cancelled = False
        self.calls: list[tuple[JsonValue, Mapping[str, Question]]] = []

    async def adecide(self, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        self.calls.append((state, questions))
        if self.hang:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.error is not None:
            raise self.error
        return SystemOneResult(model="jeeves-0.1", answers=dict.fromkeys(questions, self.answer), input_tokens=10)


def _pick(option: str, confidence: float = 0.9) -> ChoiceAnswer:
    return ChoiceAnswer(choice=option, confidence=confidence, probabilities={option: confidence})


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestRecommendIncrementalFields(SimpleTestCase):
    def setUp(self) -> None:
        incremental_field_model.cache.clear()
        TEST_clear_clients()
        TEST_reset_scripts()
        get_client().delete(f"{incremental_field_model.TEAM_BUDGET_KEY_PREFIX}:7")
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
    ) -> MagicMock:
        gateway = GatewaySystemOneClient(
            url="https://gateway.example.com/v1/systemone", api_key="test-key", headers={}, model="m", timeout=1.0
        )
        with (
            patch(f"{MODULE}.build_system_one_client", return_value=gateway),
            patch.object(GatewaySystemOneClient, "adecide", new=lambda _self, **kwargs: client.adecide(**kwargs)),
            patch(f"{MODULE}.system_one_configured", return_value=configured),
            patch(f"{MODULE}.feature_enabled_or_false", return_value=flag),
            patch(f"{MODULE}.report_team_action") as report,
        ):
            recommend_incremental_fields(schemas, team=self.team, path=WIZARD_PATH)
        return report

    def test_confident_pick_becomes_the_recommended_field(self) -> None:
        schema = _open_schema()
        client = _FakeClient(_pick("c2"))

        report = self._run([schema], client)

        assert [(f["field"], f["recommended"]) for f in schema.incremental_fields] == [
            ("fecha_actualizacion", True),
            ("created_at", False),
            ("id", False),
        ]
        assert schema.incremental_fields[0]["notes"][0] == MODEL_PICK_NOTE
        assert schema.incremental_fields[0]["picked_by_model"] is True
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
        report.assert_called_once_with(
            self.team,
            "incremental field model answered",
            {
                "path": WIZARD_PATH,
                "outcome": "ok",
                "open_tables": 1,
                "asked_tables": 1,
                "picked_tables": 1,
                "changed_defaults": 1,
            },
        )

    def test_sync_form_answer_is_reported_with_a_flushed_client(self) -> None:
        gateway = GatewaySystemOneClient(
            url="https://gateway.example.com/v1/systemone", api_key="test-key", headers={}, model="m", timeout=1.0
        )
        client = _FakeClient(_pick("c2"))
        self.team.uuid = "team-uuid"
        with (
            patch(f"{MODULE}.build_system_one_client", return_value=gateway),
            patch.object(GatewaySystemOneClient, "adecide", new=lambda _self, **kwargs: client.adecide(**kwargs)),
            patch(f"{MODULE}.system_one_configured", return_value=True),
            patch(f"{MODULE}.feature_enabled_or_false", return_value=True),
            patch(f"{MODULE}.groups", return_value={}),
            patch(f"{MODULE}.ph_scoped_capture") as scoped,
            patch(f"{MODULE}.report_team_action") as report,
        ):
            recommend_incremental_fields([_open_schema()], team=self.team, path=SYNC_FORM_PATH)

        capture = scoped.return_value.__enter__.return_value
        assert capture.call_args.kwargs["event"] == "incremental field model answered"
        assert capture.call_args.kwargs["properties"]["changed_defaults"] == 1
        report.assert_not_called()

    def test_model_can_pick_a_column_of_any_cursor_type(self) -> None:
        schema = _schema("orders", _field("created_at"), _field("seq_no", IncrementalFieldType.Integer))

        self._run([schema], _FakeClient(_pick("c1")))

        assert schema.incremental_fields[0]["field"] == "seq_no"
        assert schema.incremental_fields[0]["picked_by_model"] is True

    @parameterized.expand(
        [
            ("agrees_with_the_rules", lambda: _FakeClient(_pick("c0"))),
            ("low_confidence", lambda: _FakeClient(_pick("c1", confidence=0.4))),
            ("refusal", lambda: _FakeClient(RefusalAnswer())),
            ("option_out_of_range", lambda: _FakeClient(_pick("c9"))),
            ("gateway_error", lambda: _FakeClient(error=SystemOneRequestFailed("HTTP 529", status_code=529))),
            ("unexpected_error", lambda: _FakeClient(error=ValueError("'t0' has more than 16 options"))),
        ]
    )
    def test_unusable_answer_keeps_the_rule_based_order(
        self, _name: str, make_client: Callable[[], _FakeClient]
    ) -> None:
        client = make_client()
        schema = _open_schema()
        before = [dict(field) for field in schema.incremental_fields]

        self._run([schema], client)

        assert schema.incremental_fields == before
        assert len(client.calls) == 1

    @parameterized.expand(
        [
            ("update_column_found", _schema("orders", _field("created_at"), _field("updated_at")), {}),
            ("single_candidate", _schema("orders", _field("created_at")), {}),
            (
                "insert_only_candidates",
                _schema("orders", _field("created_at"), _field("id", IncrementalFieldType.Integer)),
                {},
            ),
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

    def test_request_past_the_deadline_is_cancelled(self) -> None:
        schema = _open_schema()
        client = _FakeClient(_pick("c2"), hang=True)

        with patch(f"{MODULE}.TIMEOUT_SECONDS", 0.01):
            self._run([schema], client)

        assert client.cancelled
        assert schema.incremental_fields[0]["field"] == "created_at"

    def test_spent_team_budget_keeps_the_rule_based_order(self) -> None:
        budget = incremental_field_model.TEAM_BUDGET
        consume(f"{incremental_field_model.TEAM_BUDGET_KEY_PREFIX}:7", budget, cost=budget.burst)
        schema = _open_schema()
        client = _FakeClient(_pick("c2"))

        report = self._run([schema], client)

        assert client.calls == []
        assert schema.incremental_fields[0]["field"] == "created_at"
        assert report.call_args.args[2]["outcome"] == "budget_exhausted"
        assert report.call_args.args[2]["asked_tables"] == 0

    def test_cached_answer_skips_the_model(self) -> None:
        first = _FakeClient(_pick("c2"))
        self._run([_open_schema()], first)
        second = _FakeClient(_pick("c2"))
        schema = _open_schema()

        self._run([schema], second)

        assert second.calls == []
        assert schema.incremental_fields[0]["field"] == "fecha_actualizacion"

    def test_cache_outage_still_applies_the_pick(self) -> None:
        schema = _open_schema()
        down = ConnectionError("cache unreachable")

        with (
            patch.object(incremental_field_model.cache, "get_many", side_effect=down),
            patch.object(incremental_field_model.cache, "set_many", side_effect=down),
        ):
            self._run([schema], _FakeClient(_pick("c2")))

        assert schema.incremental_fields[0]["field"] == "fecha_actualizacion"

    def test_unsure_answer_is_cached(self) -> None:
        self._run([_open_schema()], _FakeClient(_pick("c2", confidence=0.4)))
        second = _FakeClient(_pick("c2"))
        schema = _open_schema()

        self._run([schema], second)

        assert second.calls == []
        assert schema.incremental_fields[0]["field"] == "created_at"

    def test_one_call_asks_at_most_one_calls_worth_of_tables(self) -> None:
        schemas = [_open_schema(f"table_{n}") for n in range(40)]
        client = _FakeClient(_pick("c2"))

        self._run(schemas, client)

        assert [len(questions) for _, questions in client.calls] == [incremental_field_model.MAX_TABLES_PER_CALL]
        picked = [schema.name for schema in schemas if schema.incremental_fields[0]["field"] == "fecha_actualizacion"]
        assert picked == [f"table_{n}" for n in range(incremental_field_model.MAX_TABLES_PER_CALL)]

    def test_model_reads_a_cut_name_and_the_pick_keeps_the_full_column(self) -> None:
        long_name = "fecha_" + "x" * 4000
        schema = _schema("orders", _field("created_at"), _field(long_name), _field("id", IncrementalFieldType.Integer))
        client = _FakeClient(_pick("c2"))

        self._run([schema], client)

        state: Any = client.calls[0][0]
        assert max(len(column["name"]) for column in state["tables"]["t0"]["columns"]) == 256
        assert schema.incremental_fields[0]["field"] == long_name

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


class TestFitsOneCall(SimpleTestCase):
    @parameterized.expand(
        [
            ("nothing", [], True),
            ("one_table_of_any_width", [40], True),
            ("tables_at_the_column_limit", [16, 16], True),
            ("tables_over_the_column_limit", [16, 17], False),
            ("tables_at_the_table_limit", [1] * 8, True),
            ("tables_over_the_table_limit", [1] * 9, False),
        ]
    )
    def test_fits_one_call(self, _name: str, column_counts: list[int], expected: bool) -> None:
        assert fits_one_call(column_counts) is expected
