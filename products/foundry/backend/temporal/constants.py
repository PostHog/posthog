"""Shared constants for the foundry-run-bet workflow stack."""

from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy

# Small, fast bookkeeping writes (BetEvent inserts) — safe to retry.
RECORD_EVENT_TIMEOUT = timedelta(minutes=1)
RECORD_EVENT_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
)

# Provisioning a sandbox and running a node's command is expensive and side-effecting
# (it may spawn children of its own before returning); a transient failure is reported
# as node.failed rather than silently retried and paying for the sandbox twice.
RUN_NODE_TIMEOUT = timedelta(minutes=10)
RUN_NODE_RETRY_POLICY = RetryPolicy(maximum_attempts=1)

# Prefix a node's in-sandbox helper prints before a JSON payload on its own stdout line,
# so the activity can pick structured events (spawn_child / knowledge_published / note) out
# of otherwise-arbitrary command output.
FOUNDRY_EVENT_PREFIX = "##FOUNDRY_EVENT## "

# Installed at this path in every node's sandbox; a node's command invokes it to declare a
# child spawn, a knowledge-repo publish, or a free-form note — see activities.py. Takes its JSON
# payload base64-encoded (`foundry-event "$(echo -n '{"type":...}' | base64 -w0)"`), not raw: a
# spawned child's own "command" field can itself contain further foundry-event calls (recursion),
# and base64 has no shell-special characters at any nesting depth, so it survives being embedded
# as a JSON string value inside an outer command however many levels deep — raw JSON wrapped in
# shell quotes does not, since quoting rules don't compose across nesting levels.
FOUNDRY_EVENT_HELPER_PATH = "/usr/local/bin/foundry-event"
FOUNDRY_EVENT_HELPER_SCRIPT = f'#!/bin/sh\necho "{FOUNDRY_EVENT_PREFIX}$(echo "$1" | base64 -d)"\n'

# Where a bet's memory_repo_url (if set) is cloned into a managed node's sandbox.
FOUNDRY_MEMORY_MOUNT_PATH = "/memory"
