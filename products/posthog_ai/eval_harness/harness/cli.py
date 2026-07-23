from __future__ import annotations

import os
import argparse
from dataclasses import dataclass
from typing import Literal, cast, get_args

from .providers import DockerProviderStrategy, ModalProviderStrategy, SandboxProvider

# Bare model ids, no "anthropic/"/"openai/" prefix: the LLM gateway checks the model
# against a bare-id allowlist with startswith, so the prefixed form is rejected with a
# 403 and the agent finishes without doing anything — while still scoring exit_code_zero=1.
DEFAULT_AGENT_MODEL = "claude-opus-4-8"
DEFAULT_CODEX_AGENT_MODEL = "gpt-5.5"

# Literal mirror of products.tasks' RuntimeAdapter values: this module must stay
# Django-free (see harness/AGENTS.md), so it cannot import the enum.
AGENT_RUNTIMES = ("claude", "codex")
DEFAULT_AGENT_MODEL_BY_RUNTIME = {"claude": DEFAULT_AGENT_MODEL, "codex": DEFAULT_CODEX_AGENT_MODEL}
SkillDelivery = Literal["bundled", "exec"]
DEFAULT_SKILL_DELIVERY: SkillDelivery = "bundled"
DEFAULT_CASE_TIMEOUT_SECONDS = 60 * 15
OFFLINE_CASE_TIMEOUT_SECONDS = 60 * 60

DEFAULT_TEAM_SETUP_CONCURRENCY = 1
MANAGED_TEAM_SETUP_CONCURRENCY = 4
"""Per-case team setups allowed at once. Managed Coder and CI environments can
absorb parallel ClickHouse copies; ordinary local machines stay conservative."""

DEFAULT_ONE_SHOT_CONCURRENCY = 8
"""Concurrently running one-shot cases across all suites — bounds LLM API and
local query load the same way sandbox slots bound sandboxes."""

UNBOUNDED_SANDBOXES = 1 << 20
"""Semaphore value standing in for "no limit" — larger than any case count."""


@dataclass(frozen=True)
class HarnessOptions:
    selectors: tuple[str, ...]
    provider: SandboxProvider
    case_filter: str | None
    agent_model: str
    agent_runtime: str
    skill_delivery: SkillDelivery
    reasoning_effort: str | None
    max_sandboxes: int
    team_setup_concurrency: int
    """Concurrent team-cloning and case-seeding phases for this run."""

    keep_sandbox_containers: bool
    rebuild_sandbox_image: bool
    create_db: bool
    list_only: bool
    per_case_timeout_seconds: int
    trials: int
    fail_under: float | None
    sandbox_flags_set: tuple[str, ...]
    """Sandbox-only flags the user passed explicitly, so a run without sandboxed
    suites can reject them instead of silently ignoring them."""


def _default_case_timeout() -> int:
    if os.getenv("EVAL_MODE") == "offline":
        return OFFLINE_CASE_TIMEOUT_SECONDS
    return DEFAULT_CASE_TIMEOUT_SECONDS


def _default_team_setup_concurrency() -> int:
    if os.getenv("CODER") is not None or os.getenv("CI") is not None:
        return MANAGED_TEAM_SETUP_CONCURRENCY
    return DEFAULT_TEAM_SETUP_CONCURRENCY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m products.posthog_ai.eval_harness.harness",
        description=(
            "Run the sandboxed agent evals. Boots the shared session infrastructure once, "
            "then runs every selected suite concurrently under a single global sandbox limit."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "selectors",
        nargs="*",
        help="Substring selectors matched against '<domain>/<module>::<fn>'. Omit to run everything.",
    )
    parser.add_argument(
        "--provider",
        choices=get_args(SandboxProvider),
        default=None,
        help="Where sandboxes run (default: docker). 'modal' starts ngrok tunnels so remote sandboxes can reach this host.",
    )
    parser.add_argument("--eval", dest="case_filter", default=None, help="Only run cases whose name contains this.")
    parser.add_argument(
        "--agent-model",
        default=None,
        help=(
            f"Model the sandboxed agent runs against "
            f"(default: {DEFAULT_AGENT_MODEL} for claude, {DEFAULT_CODEX_AGENT_MODEL} for codex)."
        ),
    )
    parser.add_argument(
        "--agent-runtime",
        choices=AGENT_RUNTIMES,
        default=None,
        help="Agent runtime serving the model (default: claude). 'codex' additionally requires LLM_GATEWAY_OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--skill-delivery",
        choices=get_args(SkillDelivery),
        default=None,
        help=(
            "How product skills reach the agent. 'bundled' uses the harness's normal native skills; "
            "'exec' enables MCP skill distribution and removes native skills from every sandbox."
        ),
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="Agent reasoning effort (e.g. 'low'…'xhigh'); valid values depend on runtime+model.",
    )
    parser.add_argument(
        "--max-sandboxes",
        type=int,
        default=None,
        help=(
            f"Concurrently live sandboxes across all suites "
            f"(default: {DockerProviderStrategy.default_max_sandboxes} for docker, unbounded for modal)."
        ),
    )
    parser.add_argument(
        "--keep-sandbox-containers",
        action="store_true",
        help="Skip the end-of-run Docker container sweep, for debugging a leftover container.",
    )
    parser.add_argument(
        "--rebuild-sandbox-image",
        action="store_true",
        help="Force a rebuild of the posthog-sandbox-base image before the run (docker only).",
    )
    parser.add_argument(
        "--create-db", action="store_true", help="Rebuild the eval test database instead of reusing it."
    )
    parser.add_argument(
        "--list", dest="list_only", action="store_true", help="Print the discovered suite ids and exit."
    )
    parser.add_argument(
        "--case-timeout",
        type=int,
        default=None,
        help=f"Agent-run budget in seconds, started after team setup; must be at least 1 (default: {_default_case_timeout()}).",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Run every case this many times (Braintrust trials), to measure variance on stochastic agents.",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Exit nonzero when the mean score across all experiments falls below this fraction (0-1).",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> HarnessOptions:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Sandbox-only flags keep None/False defaults so an explicit use is
    # detectable: a run without sandboxed suites rejects them in preflight
    # instead of silently ignoring them.
    sandbox_flags_set = tuple(
        flag
        for flag, is_set in (
            ("--provider", args.provider is not None),
            ("--agent-runtime", args.agent_runtime is not None),
            ("--skill-delivery", args.skill_delivery is not None),
            ("--reasoning-effort", args.reasoning_effort is not None),
            ("--max-sandboxes", args.max_sandboxes is not None),
            ("--keep-sandbox-containers", args.keep_sandbox_containers),
            ("--rebuild-sandbox-image", args.rebuild_sandbox_image),
        )
        if is_set
    )
    provider = cast(SandboxProvider, args.provider or "docker")
    agent_runtime = args.agent_runtime or "claude"
    skill_delivery = cast(SkillDelivery, args.skill_delivery or DEFAULT_SKILL_DELIVERY)

    if args.max_sandboxes is not None and args.max_sandboxes < 1:
        parser.error("--max-sandboxes must be at least 1")
    if args.keep_sandbox_containers and provider != "docker":
        parser.error("--keep-sandbox-containers only applies to --provider docker")
    if args.rebuild_sandbox_image and provider != "docker":
        parser.error("--rebuild-sandbox-image only applies to --provider docker")
    if args.trials < 1:
        parser.error("--trials must be at least 1")
    if args.case_timeout is not None and args.case_timeout < 1:
        parser.error("--case-timeout must be at least 1")

    # A runtime/model mismatch otherwise surfaces minutes into the run as an opaque
    # gateway 403, with the agent finishing without doing anything.
    agent_model = args.agent_model or DEFAULT_AGENT_MODEL_BY_RUNTIME[agent_runtime]
    if agent_runtime == "codex" and agent_model.startswith("claude"):
        parser.error(f"--agent-model {agent_model} is a Claude model; the codex runtime serves gpt-* models")
    if agent_runtime == "claude" and agent_model.startswith("gpt"):
        parser.error(f"--agent-model {agent_model} is an OpenAI model; pass --agent-runtime codex to serve it")
    if args.fail_under is not None and not (0 < args.fail_under <= 1):
        parser.error("--fail-under must be greater than 0 and at most 1")

    default_slots = (
        DockerProviderStrategy.default_max_sandboxes
        if provider == "docker"
        else ModalProviderStrategy.default_max_sandboxes
    )
    max_sandboxes = args.max_sandboxes or default_slots or UNBOUNDED_SANDBOXES

    return HarnessOptions(
        selectors=tuple(args.selectors),
        provider=provider,
        case_filter=args.case_filter,
        agent_model=agent_model,
        agent_runtime=agent_runtime,
        skill_delivery=skill_delivery,
        reasoning_effort=args.reasoning_effort,
        max_sandboxes=max_sandboxes,
        team_setup_concurrency=_default_team_setup_concurrency(),
        keep_sandbox_containers=args.keep_sandbox_containers,
        rebuild_sandbox_image=args.rebuild_sandbox_image,
        create_db=args.create_db,
        list_only=args.list_only,
        per_case_timeout_seconds=args.case_timeout if args.case_timeout is not None else _default_case_timeout(),
        trials=args.trials,
        fail_under=args.fail_under,
        sandbox_flags_set=sandbox_flags_set,
    )
