"""Composite risk-score analysis for a pull request.

Mixes deterministic heuristics (diff size, surface area of risky paths, test
coverage of the change) with an LLM-judged sub-score, into a single 0-100
score plus a per-factor breakdown. Cached in Redis keyed by `head_sha` so
new commits invalidate the cache.
"""

from __future__ import annotations

import re
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from posthog.models import Team, User
from posthog.models.integration import GitHubIntegration, Integration
from posthog.redis import get_client

from ee.hogai.llm import MaxChatAnthropic

logger = structlog.get_logger(__name__)


CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days; staleness shown to user via head_sha in payload

DIFF_CHAR_CAP_PER_FILE = 6_000
DIFF_TOTAL_CHAR_CAP = 60_000

# Path patterns whose mere presence in the diff raises the surface-area score.
HIGH_RISK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(^|/)migrations?/"), "database migration"),
    (re.compile(r"\.sql$"), "raw SQL"),
    (re.compile(r"(^|/)(auth|authn|authz|login|session|jwt|oauth)\b", re.IGNORECASE), "auth-adjacent"),
    (re.compile(r"(^|/)(billing|payment|pricing|invoice|stripe)\b", re.IGNORECASE), "billing / payments"),
    (re.compile(r"(^|/)settings/"), "Django settings"),
    (re.compile(r"(^|/)(infra|deploy|kustomize|helm|terraform)/", re.IGNORECASE), "infra / deploy"),
    (re.compile(r"\.github/workflows/"), "CI workflow"),
    (re.compile(r"(^|/)Dockerfile|\.dockerignore$|docker-compose"), "container image"),
    (re.compile(r"(^|/)posthog/api/"), "core API"),
]


TEST_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|/)tests?/"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"\.test\.[jt]sx?$"),
    re.compile(r"\.spec\.[jt]sx?$"),
    re.compile(r"(^|/)__tests__/"),
]


SYSTEM_PROMPT = """You are a senior security & infrastructure reviewer assessing the merge risk
of a pull request. Be honest, concrete, and discriminating. The reviewer needs DIFFERENT scores
for different PRs — flagging every change as "high" is as unhelpful as flagging none.

You will receive: PR title, body, file list with status (added/modified/removed/renamed), and a
unified patch per file (possibly truncated). Judge ONLY from the diff content provided.

Output a sub-score 0-100 (higher = more dangerous) plus a 2-3 sentence rationale and a one-line
headline.

CORE PRINCIPLE — DANGER LIVES IN ACTIONS, NOT FILE PATHS
A new endpoint inside an `auth/` directory is not automatically risky; *disabling* an auth check
is. A new query-param on an existing API is not risky; *removing input validation* is. Score on
what the diff actually DOES, not where it lives.

BAND DEFINITIONS — pick the band whose description matches the actual change.

0-25  (safe)
- Pure docs, comments, markdown, copy edits.
- Data-only changes: seed scripts, fixtures, content rows. No schema change.
- Pure cosmetic UI: CSS, spacing, colours, icons, with no logic change.
- Test additions (new tests, no deletions).
- New static pages, new feature-flag-gated rollouts of inert UI.

26-55  (medium — routine feature work)
- New API endpoint / new view / new query-param that uses existing auth and validation patterns.
- New feature behind a feature flag, business-logic additions in product code.
- Refactors that preserve behaviour.
- New PostHog event captures with already-public properties.
- Wiring up an existing model into a new flow (e.g. exposing an existing relation via an
  endpoint that respects the same permissions as siblings).
- Anything where you'd say "this could regress a feature" but not "this could leak data,
  corrupt state, or break the security boundary".

56-79  (high — concrete blast radius)
- Sends PII (email, IP, full name, last_login, device id) to an EXTERNAL third party (e.g.
  Segment, Mixpanel, Google Analytics, HubSpot, Salesforce, Slack). DO NOT flag sending data
  to PostHog itself — PostHog is the first-party analytics destination for this codebase and
  sending PII to PostHog `identify` / `capture` is expected behaviour, not a risk signal.
- New endpoint that takes user input and reaches a sensitive sink (file system, shell,
  template render, ORM `extra()`) without obvious sanitisation.
- Schema migration with a default-NOT-NULL backfill on a large table, or a column rename
  without a multi-step plan.
- Removes a unit test, assertion, or guard for non-trivial code.
- Adds `# type: ignore` / `eslint-disable` / `--no-verify` to hide a real error rather than a
  framework quirk.
- Changes the request/response contract of a public API in a backwards-incompatible way.
- Loosens (but does not fully disable) auth/CSRF/rate-limits (e.g. expands an allowlist).

80-100  (critical — incident-shaped, ship-stopping)
- Exposes / prints / echoes / logs / commits a secret, token, credential, API key, private key,
  or password. Includes `echo $GITHUB_TOKEN`, `printenv`, `set -x` with secrets in env,
  `${{SECRETS.*}}` substitution into shell output, or embedding a secret in a URL written to
  CI/build logs.
- Raw SQL constructed by string concatenation / interpolation of user input (`f"... WHERE
  name LIKE '%{{q}}%'"`, `cursor.execute("... " + user_input)`) — SQL injection.
- Removes authentication, CSRF protection, signed-URL verification, webhook signature checks,
  or RBAC gates from a public endpoint.
- Weakens crypto: `verify=False`, accept-any-TLS-cert, downgrading password hashes, disabling
  certificate verification, hardcoded crypto keys.
- Destructive SQL without a guard: `DROP TABLE`, `TRUNCATE`, unbounded `DELETE`/`UPDATE`.
- CI privilege escalation: `pull_request_target` running untrusted code with secrets,
  `permissions: write-all`, new self-hosted runner accepting untrusted PRs.
- Hardcoded production credentials or production endpoints committed to source.
- Removes the ONLY input validation between an external boundary and a dangerous sink.

CALIBRATION CHECKS — apply before returning:
- Did you reach for "high" because the file path looks scary, or because the diff actually does
  something dangerous? If only the former, drop to medium.
- Did you score below 80 a change that prints a real secret to logs, runs raw user input as SQL,
  or removes authentication on a public route? If yes, raise it.
- Did you score above 25 a pure data-seed PR or pure CSS change? If yes, lower it.
- Be willing to say "safe". The point of this widget is for "high" to MEAN something.

Return strictly the JSON schema requested — no prose outside JSON.

{format_instructions}
"""


USER_PROMPT = """PR title: {pr_title}

PR body:
{pr_body}

Files ({file_count}):
{file_list}

Patch (possibly truncated):
{patch_blob}
"""


@dataclass(frozen=True)
class RiskFactor:
    key: str
    label: str
    score: int  # 0-100
    weight: float  # contribution weight; weights need not sum to 1, normalized at use
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskScoreResult:
    repository: str
    pr_number: int
    head_sha: str
    base_sha: str
    score: int
    level: str  # low | moderate | high | critical
    headline: str
    rationale: str
    factors: list[RiskFactor] = field(default_factory=list)
    truncated: bool = False
    computed_at: str = ""

    def to_response(self, *, cached: bool) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "pr_number": self.pr_number,
            "head_sha": self.head_sha,
            "base_sha": self.base_sha,
            "score": self.score,
            "level": self.level,
            "headline": self.headline,
            "rationale": self.rationale,
            "factors": [f.to_dict() for f in self.factors],
            "truncated": self.truncated,
            "cached": cached,
            "computed_at": self.computed_at,
        }


class _LLMRiskJudgment(BaseModel):
    score: int = Field(ge=0, le=100, description="Qualitative risk sub-score 0-100")
    headline: str = Field(description="One-line summary of the dominant risk in this PR (or 'Low risk' if trivial)")
    rationale: str = Field(description="2-3 sentence rationale for the score")


# Bump when prompt calibration or composite logic changes so existing cached
# scores are abandoned and the next read recomputes under the new rules.
CACHE_KEY_VERSION = "v6"


def _redis_cache_key(team_id: int, repository: str, pr_number: int) -> str:
    return f"githog:risk_score:{CACHE_KEY_VERSION}:{team_id}:{repository.lower()}:{pr_number}"


def _level_for_score(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 35:
        return "moderate"
    return "low"


def _diff_size_factor(files: list[dict[str, Any]]) -> RiskFactor:
    total_changes = sum(int(f.get("additions") or 0) + int(f.get("deletions") or 0) for f in files)
    file_count = len(files)
    # Tunable curves; saturate ~2000 line changes / ~40 files.
    line_score = min(100, int((total_changes / 2000) * 100))
    file_score = min(100, int((file_count / 40) * 100))
    score = max(line_score, file_score)
    detail = f"{total_changes} line changes across {file_count} files"
    return RiskFactor(key="diff_size", label="Diff size", score=score, weight=0.15, detail=detail)


def _surface_area_factor(files: list[dict[str, Any]]) -> RiskFactor:
    matched: list[str] = []
    seen_labels: set[str] = set()
    for f in files:
        filename = str(f.get("filename") or "")
        for pattern, label in HIGH_RISK_PATTERNS:
            if pattern.search(filename) and label not in seen_labels:
                matched.append(label)
                seen_labels.add(label)
                break
    # Each distinct high-risk category adds 20 points, capped at 100.
    score = min(100, 20 * len(matched))
    if matched:
        detail = "Touches " + ", ".join(matched)
    else:
        detail = "No high-risk paths matched"
    return RiskFactor(key="surface_area", label="Surface area", score=score, weight=0.25, detail=detail)


def _test_coverage_factor(files: list[dict[str, Any]]) -> RiskFactor:
    """Inverse of test coverage — lots of non-test code with no accompanying tests = high score."""
    if not files:
        return RiskFactor(key="test_coverage", label="Test coverage", score=0, weight=0.20, detail="No files changed")
    non_test = 0
    test = 0
    for f in files:
        filename = str(f.get("filename") or "")
        if any(p.search(filename) for p in TEST_PATH_PATTERNS):
            test += 1
        else:
            non_test += 1
    if non_test == 0:
        return RiskFactor(
            key="test_coverage",
            label="Test coverage",
            score=0,
            weight=0.20,
            detail=f"Test-only change ({test} test files)",
        )
    if test == 0:
        return RiskFactor(
            key="test_coverage",
            label="Test coverage",
            score=80,
            weight=0.20,
            detail=f"No test files touched ({non_test} non-test files)",
        )
    ratio = test / non_test
    # ratio >= 1 (parity) → 10; ratio 0.5 → 35; ratio 0.25 → 55; ratio < 0.1 → 75
    score = max(10, min(80, int(80 - 70 * min(1.0, ratio))))
    detail = f"{test} test file{'s' if test != 1 else ''} for {non_test} non-test file{'s' if non_test != 1 else ''}"
    return RiskFactor(key="test_coverage", label="Test coverage", score=score, weight=0.20, detail=detail)


def _truncate(text: str, cap: int) -> tuple[str, bool]:
    if len(text) <= cap:
        return text, False
    return text[:cap] + "\n…<truncated>…\n", True


def _build_patch_blob(files: list[dict[str, Any]]) -> tuple[str, bool]:
    chunks: list[str] = []
    truncated_any = False
    used = 0
    for f in files:
        if used >= DIFF_TOTAL_CHAR_CAP:
            truncated_any = True
            break
        patch = f.get("patch") or ""
        if not patch:
            continue
        body, did = _truncate(patch, DIFF_CHAR_CAP_PER_FILE)
        truncated_any = truncated_any or did
        header = f"### {f.get('filename')} ({f.get('status')})"
        chunks.append(f"{header}\n```diff\n{body}\n```")
        used += len(body)
    blob = "\n\n".join(chunks) if chunks else "<no patch content>"
    return blob, truncated_any


def _file_list_blob(files: list[dict[str, Any]]) -> str:
    return (
        "\n".join(
            f"- {f.get('filename')} ({f.get('status')}, +{f.get('additions', 0)}/-{f.get('deletions', 0)})"
            for f in files
        )
        or "<no files>"
    )


def _llm_judgment_factor(
    *,
    team: Team,
    user: User,
    pr_title: str,
    pr_body: str,
    files: list[dict[str, Any]],
) -> tuple[RiskFactor, str, str, bool]:
    """Returns (factor, headline, rationale, truncated)."""
    patch_blob, patch_truncated = _build_patch_blob(files)
    file_list = _file_list_blob(files)

    parser = PydanticOutputParser(pydantic_object=_LLMRiskJudgment)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("user", USER_PROMPT),
        ]
    ).partial(format_instructions=parser.get_format_instructions())

    model = MaxChatAnthropic(
        model="claude-sonnet-4-5",
        temperature=0.2,
        max_tokens=1024,
        user=user,
        team=team,
        billable=True,
        streaming=False,
        disable_streaming=True,
        inject_context=False,
    )

    chain = prompt | model | parser

    try:
        result: _LLMRiskJudgment = chain.invoke(
            {
                "pr_title": pr_title or "",
                "pr_body": pr_body or "",
                "file_count": len(files),
                "file_list": file_list,
                "patch_blob": patch_blob,
            }
        )
    except Exception as exc:
        logger.warning("githog.risk_score: LLM judgment failed; falling back to neutral", error=str(exc))
        factor = RiskFactor(
            key="ai_judgment",
            label="AI judgment",
            score=40,
            weight=0.40,
            detail="LLM unavailable; using neutral default",
        )
        return (
            factor,
            "Risk assessment partially unavailable",
            "Automated review failed to produce a judgment.",
            patch_truncated,
        )

    factor = RiskFactor(
        key="ai_judgment",
        label="AI judgment",
        score=int(result.score),
        weight=0.40,
        detail=result.headline,
    )
    return factor, result.headline, result.rationale, patch_truncated


def _composite_score(factors: list[RiskFactor]) -> int:
    total_weight = sum(f.weight for f in factors) or 1.0
    weighted = sum(f.score * f.weight for f in factors)
    return max(0, min(100, int(round(weighted / total_weight))))


def _try_get_cache(redis_client: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = redis_client.get(key)
    except RedisError as exc:
        logger.warning("githog.risk_score: redis get failed", error=str(exc))
        return None
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (ValueError, TypeError):
        return None


def _try_set_cache(redis_client: Any, key: str, payload: dict[str, Any]) -> None:
    try:
        redis_client.setex(key, CACHE_TTL_SECONDS, json.dumps(payload))
    except (RedisError, TypeError) as exc:
        logger.warning("githog.risk_score: redis set failed", error=str(exc))


def compute_risk_score(
    *,
    team: Team,
    user: User,
    integration: Integration,
    repository: str,
    pr_number: int,
    refresh: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Compute (or fetch cached) risk score. Returns (response_dict, was_cached).

    Cached payload format matches the API response shape exactly so we can
    serve straight from cache without re-deriving anything.
    """
    redis_client = get_client()
    cache_key = _redis_cache_key(team.pk, repository, pr_number)

    # Fast path: serve cached payload without any GitHub call. Staleness is
    # surfaced to the UI via the head_sha shown alongside the score.
    if not refresh:
        cached = _try_get_cache(redis_client, cache_key)
        if cached is not None:
            cached_response = {**cached, "cached": True}
            return cached_response, True

    github = GitHubIntegration(integration)
    _, _, repo_name = repository.partition("/")

    pr_meta = github.get_pull_request(repo_name, pr_number)
    if not pr_meta.get("success"):
        raise ValueError(pr_meta.get("error") or "Failed to fetch PR metadata")

    head_sha: str = pr_meta["head_sha"]
    base_sha: str = pr_meta["base_sha"]

    files_result = github.list_pull_request_files(repo_name, pr_number)
    if not files_result.get("success"):
        raise ValueError(files_result.get("error") or "Failed to list PR files")
    files: list[dict[str, Any]] = files_result.get("files") or []

    factors: list[RiskFactor] = [
        _diff_size_factor(files),
        _surface_area_factor(files),
        _test_coverage_factor(files),
    ]
    ai_factor, headline, rationale, truncated = _llm_judgment_factor(
        team=team,
        user=user,
        pr_title=pr_meta.get("title") or "",
        pr_body=pr_meta.get("body") or "",
        files=files,
    )
    factors.append(ai_factor)

    score = _composite_score(factors)
    level = _level_for_score(score)

    # AI-judgment veto: a small-diff change can still be catastrophic (a leaked
    # secret in CI, an auth bypass, a destructive migration). The deterministic
    # factors don't see those — they see "small PR touching one CI file" and
    # average down. If the LLM is genuinely alarmed (its own >=80 band), trust
    # it over the math; for the AI's own "high" band (>=60), lift to high
    # unless the composite already says so. Above those thresholds we leave
    # the composite alone — the prompt is discriminating enough now.
    ai_score = int(ai_factor.score)
    if ai_score >= 85 and level != "critical":
        level = "critical"
    elif ai_score >= 65 and level not in ("critical", "high"):
        level = "high"

    if not headline:
        headline = {
            "critical": "Critical risk — review carefully before merge",
            "high": "High risk — multiple risk factors detected",
            "moderate": "Moderate risk — typical PR",
            "low": "Low risk — small or well-isolated change",
        }[level]

    result = RiskScoreResult(
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        base_sha=base_sha,
        score=score,
        level=level,
        headline=headline,
        rationale=rationale,
        factors=factors,
        truncated=truncated,
    )
    response = result.to_response(cached=False)
    # Store with computed_at set by the consumer; we keep it empty here and let
    # the cache TTL serve as the freshness signal.
    _try_set_cache(redis_client, cache_key, {**response, "cached": False})
    return response, False
