import json
from hashlib import sha256

from products.wizard.backend.facade.contracts import CreateWizardRunInput
from products.wizard.backend.logic.runs.mappers import workspace_to_record


def create_run_request_fingerprint(params: CreateWizardRunInput) -> str:
    workspace_type, workspace = workspace_to_record(params.workspace)

    value = {
        "environment": params.environment.value,
        "program_id": params.program_id,
        "wizard_version": params.wizard_version,
        "workspace": workspace,
        "workspace_type": workspace_type.value,
    }

    return sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
