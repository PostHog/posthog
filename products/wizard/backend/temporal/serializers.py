import json
from uuid import UUID

from products.wizard.backend.temporal.contracts import WizardRunActivityInput


def deserialize_workflow_input(inputs: list[str]) -> WizardRunActivityInput:
    value = json.loads(inputs[0])
    return WizardRunActivityInput(
        team_id=value["team_id"],
        run_id=UUID(value["run_id"]),
        use_local_wizard_source=value.get("use_local_wizard_source") is True,
    )
