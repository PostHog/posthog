from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID

from pydantic import JsonValue

from posthog.cdp.filters import compile_filters_bytecode
from posthog.cdp.validation import compile_hog

from products.cdp.backend.facade.models import HogFunction, HogFunctionType
from products.posthog_ai.eval_harness.environment.guard import assert_local_databases
from products.posthog_ai.eval_harness.environment.schema import EnvironmentModel

if TYPE_CHECKING:
    from posthog.models import Team, User


class EnvironmentIngestion(EnvironmentModel):
    id: UUID
    hog: Literal["return null"] = "return null"
    bytecode: list[JsonValue]
    filters: dict[str, JsonValue]
    template_id: Literal["template-drop-events"] = "template-drop-events"
    type: Literal["transformation"] = "transformation"
    enabled: Literal[True] = True
    deleted: Literal[False] = False
    execution_order: Literal[0] = 0

    @classmethod
    def install(cls, team: Team, user: User) -> Self:
        assert_local_databases()
        hog = "return null"
        function = HogFunction.objects.create(
            team_id=team.id,
            created_by_id=user.id,
            name="Keep the prepared event dataset unchanged",
            description="Drop captured events in this local evaluation project. Prepared events are imported directly.",
            type=HogFunctionType.TRANSFORMATION,
            template_id="template-drop-events",
            hog=hog,
            bytecode=compile_hog(hog, HogFunctionType.TRANSFORMATION),
            inputs={},
            inputs_schema=[],
            filters={},
            execution_order=0,
            enabled=True,
            deleted=False,
        )
        protection = cls(id=function.id, bytecode=function.bytecode, filters=function.filters)
        protection.verify(team)
        return protection

    def verify(self, team: Team) -> None:
        assert_local_databases()
        function = HogFunction.objects.filter(id=self.id, team_id=team.id).first()
        expected = self.model_dump(exclude={"id"})
        if (
            function is None
            or self.bytecode != compile_hog(self.hog, HogFunctionType.TRANSFORMATION)
            or self.filters != compile_filters_bytecode({}, team)
            or any(getattr(function, field) != value for field, value in expected.items())
            or function.inputs != {}
            or function.inputs_schema != []
            or function.encrypted_inputs not in (None, {})
            or function.mappings is not None
            or function.masking is not None
        ):
            raise ValueError(
                "The environment event-ingestion protection is missing or changed; restore into a fresh workspace."
            )
