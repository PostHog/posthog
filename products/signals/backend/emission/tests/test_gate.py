import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.signals.backend.emission.gate import emit_signals_enabled
from products.signals.backend.models import SignalSourceConfig, SignalTeamConfig

ZENDESK_SOURCE_TYPE = "Zendesk"
ZENDESK_SCHEMA_NAME = "tickets"


@pytest.mark.django_db
class TestEmitSignalsGate(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.ZENDESK,
            source_type=SignalSourceConfig.SourceType.TICKET,
            enabled=True,
        )

    def _gate(self) -> bool:
        return emit_signals_enabled(
            self.team.id, ZENDESK_SOURCE_TYPE, ZENDESK_SCHEMA_NAME, ai_data_processing_approved=True
        )

    @parameterized.expand([(True,), (False,), (None,)])
    def test_self_driving_switch_gates_data_import_emission(self, autostart_enabled: bool | None) -> None:
        # The gate runs before the emission child workflow is spawned, and that workflow pays for LLM
        # summarization and actionability filtering on every imported record — so an opted-out team
        # has to be turned away here, not only later at `emit_signal`.
        # `None` is the shape every team starts in: the team extension signal creates the row with
        # the switch unset, and that has to read as on.
        SignalTeamConfig.objects.update_or_create(team=self.team, defaults={"autostart_enabled": autostart_enabled})

        assert self._gate() is (autostart_enabled is not False)
