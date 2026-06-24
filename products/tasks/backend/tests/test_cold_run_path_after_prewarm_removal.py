"""Regression guard for the bare-sandbox prewarm removal.

Agent warming (an idling Run via SandboxWarmer) replaced the bare-sandbox prewarm. After that
removal there must be exactly one provisioning path: the cold path that boots a fresh sandbox, then
clones and checks out. These tests fail closed if any prewarm artifact creeps back — a lingering
``prewarmed_sandbox_id`` field, a leased-box branch in the provision activity, or the deleted
prewarm modules being reintroduced.
"""

import inspect
import importlib
import dataclasses

from django.test import SimpleTestCase

from products.tasks.backend.temporal.process_task import workflow as workflow_module
from products.tasks.backend.temporal.process_task.activities import provision_sandbox

PREWARM_TOKENS = ("prewarmed_sandbox_id", "prewarmed_sandbox", "seeded_env", "lease_prewarmed")


class TestPrewarmArtifactsRemoved(SimpleTestCase):
    def test_prewarm_modules_are_gone(self):
        for module_path in (
            "products.tasks.backend.logic.services.prewarmed_sandbox",
            "products.tasks.backend.temporal.prewarm_sandbox",
        ):
            with self.assertRaises(ModuleNotFoundError, msg=f"{module_path} should have been removed"):
                importlib.import_module(module_path)

    def test_process_task_input_has_no_prewarm_field(self):
        field_names = {f.name for f in dataclasses.fields(workflow_module.ProcessTaskInput)}
        assert "prewarmed_sandbox_id" not in field_names
        assert not (field_names & set(PREWARM_TOKENS))

    def test_cold_provision_input_types_have_no_prewarm_field(self):
        for input_cls in (
            provision_sandbox.CreateSandboxForRepositoryInput,
            provision_sandbox.CloneRepositoryInSandboxInput,
            provision_sandbox.CheckoutBranchInSandboxInput,
        ):
            field_names = {f.name for f in dataclasses.fields(input_cls)}
            assert not (field_names & set(PREWARM_TOKENS)), f"{input_cls.__name__} still references a prewarm field"


class TestColdProvisionPathIntact(SimpleTestCase):
    def test_create_activity_cold_creates_via_sandbox_create(self):
        source = inspect.getsource(provision_sandbox.create_sandbox_for_repository)
        assert "Sandbox.create(config)" in source
        for token in PREWARM_TOKENS:
            assert token not in source, f"create_sandbox_for_repository still references {token}"

    def test_workflow_runs_create_then_clone_then_checkout(self):
        source = inspect.getsource(workflow_module.ProcessTaskWorkflow._get_sandbox_for_repository)
        create_at = source.index("create_sandbox_for_repository,")
        clone_at = source.index("clone_repository_in_sandbox,")
        checkout_at = source.index("checkout_branch_in_sandbox,")
        assert create_at < clone_at < checkout_at

    def test_no_prewarm_references_in_provision_or_workflow_source(self):
        for module in (provision_sandbox, workflow_module):
            source = inspect.getsource(module)
            for token in PREWARM_TOKENS:
                assert token not in source, f"{module.__name__} still references {token}"
