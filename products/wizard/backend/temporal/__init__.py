from products.wizard.backend.temporal.activities.execution import execute_wizard
from products.wizard.backend.temporal.activities.handoff import create_run_artifacts
from products.wizard.backend.temporal.activities.lifecycle import finalize_run
from products.wizard.backend.temporal.activities.local_package import prepare_local_wizard
from products.wizard.backend.temporal.activities.workspace import clone_repository, destroy_worker, provision_worker
from products.wizard.backend.temporal.workflows.execute_run import ExecuteWizardRunWorkflow

WORKFLOWS = [ExecuteWizardRunWorkflow]

ACTIVITIES = [
    provision_worker,
    prepare_local_wizard,
    clone_repository,
    execute_wizard,
    create_run_artifacts,
    destroy_worker,
    finalize_run,
]
