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
# `printf '%s'`, not `echo`, for the decoded payload: on a `/bin/sh` that's dash (as in the
# slim sandbox image), the builtin `echo` interprets backslash escapes by default — so a
# payload whose JSON contains an escaped newline (`\n`, two characters, from any multi-line
# `command` value, e.g. a real shell script) gets its `\n` turned into an ACTUAL newline on
# output. That splits one JSON line into many, and only the first (an incomplete fragment)
# starts with the sentinel prefix, so the event silently fails to parse. `printf '%s'` never
# interprets escapes in its arguments (only in its own format string), so the decoded bytes
# come out exactly as encoded.
FOUNDRY_EVENT_HELPER_SCRIPT = "#!/bin/sh\nprintf '%s%s\\n' '" + FOUNDRY_EVENT_PREFIX + '\' "$(echo "$1" | base64 -d)"\n'

# Where a bet's memory_repo_url (if set) is cloned into a managed node's sandbox.
FOUNDRY_MEMORY_MOUNT_PATH = "/memory"

# Where a build-loop node's target_repo (see build_workflow.py) is cloned in its sandbox.
FOUNDRY_TARGET_REPO_PATH = "/repo"

# `npm install -g` is run once per build-loop node before its command, rather than baking
# a dedicated sandbox image layer — SLIM_BASE already ships git+node+uv (its own Dockerfile
# comment anticipates "node (Claude Code CLI runtime)"); see build_workflow.py's module
# docstring for the full tradeoff.
FOUNDRY_CLAUDE_CLI_PACKAGE = "@anthropic-ai/claude-code"

# Claude Code's --dangerously-skip-permissions refuses to run as root/sudo (a real check
# discovered by dry-running the real sandbox image before trusting it in a full bet run —
# see build_workflow.py's module docstring). Sandboxes provision as root, so a build-loop
# node's command runs as this unprivileged user instead, created fresh in every sandbox.
FOUNDRY_AGENT_USER = "foundry-agent"
