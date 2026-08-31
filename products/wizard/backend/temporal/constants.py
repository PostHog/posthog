from uuid import UUID

EXECUTE_WIZARD_RUN_WORKFLOW = "execute-wizard-run"


def wizard_run_workflow_id(run_id: UUID) -> str:
    return f"wizard-run-{run_id}"
