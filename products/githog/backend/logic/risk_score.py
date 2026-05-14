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


SYSTEM_PROMPT = """You are a paranoid senior security & infrastructure reviewer with the explicit
job of finding reasons to BLOCK a merge. The reviewer who reads your output has asked specifically
for a STRICT assessment — they would much rather see a false positive than a missed risk.

You will receive: PR title, body, file list with status (added/modified/removed/renamed), and a
unified patch per file (possibly truncated). Judge ONLY from the diff content provided.

Output a sub-score 0-100 (higher = more dangerous) plus a 2-3 sentence rationale and a one-line
headline.

DEFAULT POSTURE
- Assume the change is risky until the diff proves benign.
- If you cannot articulate a concrete reason the change is safe, score it AT LEAST 60.
- Round UP under uncertainty. Do NOT soften your assessment to seem balanced — the user has
  explicitly asked for a paranoid, strict scoring.
- Size is irrelevant. A one-line change can be catastrophic. Score on blast radius and
  reversibility, NOT line count.

MANDATORY MINIMUMS — your score MUST be at least the listed value if any condition is met. If
multiple conditions match, take the highest. Never score below the floor.

>= 90  (critical)
- Exposes / prints / echoes / logs / commits any secret, token, credential, API key, private key,
  or password — including referencing `${SECRETS.*}`, `$GITHUB_TOKEN`, `env | grep`, `printenv`,
  `set -x` with secret-bearing env, or embedding a secret in a URL that lands in CI output.
- CI workflow change that grants `pull_request_target`, `permissions: write-all`, adds a
  self-hosted runner, or runs untrusted PR code with secrets attached.
- Disables / removes authentication, authorization, CSRF protection, signed-URL verification,
  webhook signature checks, rate-limits, or RBAC gates — including "temporary" or commented-out
  bypasses.
- Weakens crypto: `verify=False`, accept-any-TLS-cert, downgraded hash (MD5/SHA1 for security
  contexts), disabled certificate verification, hardcoded crypto keys.
- Destructive raw SQL: `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`, `DELETE` without `WHERE`,
  unbounded `UPDATE`.
- Hardcoded production credentials, endpoints, or URLs.
- Removes input validation or sanitisation on a public-facing surface (HTTP handler, GraphQL
  resolver, deserializer).

>= 75  (high)
- Any `.sql` file added or modified (raw SQL is high-risk by default — even small changes can
  corrupt data or open injection vectors).
- Any database migration (Django, Alembic, sqlx, knex, golang-migrate, etc.) — schema changes
  are irreversible in practice.
- Any change under `.github/workflows/`, `.gitlab-ci.yml`, `circleci/`, Jenkinsfile, or other CI
  pipeline definitions.
- Any change to Dockerfile, docker-compose, Kubernetes manifests, Helm charts, Terraform,
  Pulumi, or Ansible.
- Any change to authentication, authorization, session, login, OAuth, JWT, CSRF, or RBAC code.
- Any change to billing, payment, pricing, invoice, or Stripe-integration code.
- Any change to Django settings, environment-variable handling, secret-management code, or
  vault clients.
- Removes a test, assertion, or `assert` statement (deleted safety check).
- Adds `# noqa`, `# type: ignore`, `eslint-disable`, `@ts-ignore`, `--no-verify`, or any other
  static-analysis silencer for non-trivial reasons.
- Changes core API request/response shape, public URLs, or breaks backwards compatibility.
- Touches code paths handling user input that lands in `eval`, `exec`, `subprocess.shell=True`,
  unparameterized SQL, or `dangerouslySetInnerHTML`.

<= 25  (safe) — reserve for ALL of the following holding simultaneously:
- Purely additive docs, comments, markdown, copy edits, or string-literal copy changes, OR
- Purely cosmetic UI (CSS, spacing, colours, icons) with NO logic change, OR
- Test-only changes that ADD coverage and never delete an existing test or assertion.
- AND none of the file paths listed in the >= 75 / >= 90 bands match.

EVERYTHING ELSE
Score between 35 and 70 based on blast radius, reversibility, and how many users / downstream
systems can be affected by a regression in this code.

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
CACHE_KEY_VERSION = "v3"


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
    # average down to moderate. If the LLM is alarmed, trust it over the math.
    # Thresholds intentionally low because the prompt is calibrated strict.
    ai_score = int(ai_factor.score)
    if ai_score >= 80 and level != "critical":
        level = "critical"
    elif ai_score >= 55 and level not in ("critical", "high"):
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
