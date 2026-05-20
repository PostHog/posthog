"""DRF serializers for wizard. Bound to facade DTOs, not Django models."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.wizard.backend.facade.contracts import UpsertWizardSessionRequest, WizardSessionDTO


class WizardSessionSerializer(DataclassSerializer):
    """Output: serialises a WizardSessionDTO returned by the facade."""

    class Meta:
        dataclass = WizardSessionDTO


class UpsertWizardSessionRequestSerializer(DataclassSerializer):
    """Input: validates the JSON the wizard CLI posts. team_id is derived from URL."""

    class Meta:
        dataclass = UpsertWizardSessionRequest
