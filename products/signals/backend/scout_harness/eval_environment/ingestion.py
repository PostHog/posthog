from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.models import Team

from products.cdp.backend.facade.models import HogFunction

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.environment.restore import EnvironmentReceipt


class ScoutEnvironmentIngestion:
    NAME = "Event ingestion policy"
    DESCRIPTION = "Ignore incoming events for this project."

    @staticmethod
    def _function(receipt: EnvironmentReceipt) -> HogFunction:
        if receipt.team_id is None or receipt.event_ingestion is None:
            raise ValueError("The prepared scout environment has no event-ingestion protection.")
        team = Team.objects.get(id=receipt.team_id)
        receipt.event_ingestion.verify(team)
        return HogFunction.objects.get(id=receipt.event_ingestion.id, team_id=receipt.team_id)

    @classmethod
    def prepare(cls, receipt: EnvironmentReceipt) -> None:
        function = cls._function(receipt)
        if (function.name, function.description) != (cls.NAME, cls.DESCRIPTION):
            HogFunction.objects.filter(id=function.id, team_id=function.team_id).update(
                name=cls.NAME, description=cls.DESCRIPTION
            )

    @classmethod
    def verify(cls, receipt: EnvironmentReceipt) -> None:
        function = cls._function(receipt)
        if (function.name, function.description) != (cls.NAME, cls.DESCRIPTION):
            raise ValueError(
                "The event-ingestion policy labels changed; run prepare before evaluating this environment."
            )
