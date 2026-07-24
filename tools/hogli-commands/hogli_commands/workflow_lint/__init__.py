"""Workflow lint package: framework + checks for `.github/workflows/**` policies.

The CLI entrypoint is wired via the ``click:`` manifest entry in ``hogli.yaml``;
the lazy loader resolves ``hogli_commands.workflow_lint.cli:cmd_lint_workflows``
on demand. To run from the command line:

    bin/hogli lint:workflows
    bin/hogli lint:workflows --check WF001
    bin/hogli lint:workflows --list
"""
