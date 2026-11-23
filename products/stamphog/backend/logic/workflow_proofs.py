"""Turn a workflow publisher's signed check run into a check run the engine can trust.

An attestation entry may name a default-branch `workflow`, its publishing `job` and the `events` it
runs on instead of an `app_id`. Any job's built-in token can create a check run under any name, and
can edit any other check run that a workflow wrote. So nothing the Checks API returns says which job
wrote it. The publishing job therefore signs its result with a GitHub Actions OIDC ID token, and posts
the marker and the token in the check run's summary:

    <!-- stamphog:v1 {"files": [...], "pr": N, "head_sha": "...", "merge_base": "...", "blobs": {...}} -->
    <!-- stamphog-oidc:v1 <token> -->

The token's audience is `proof_audience(check, conclusion, marker)`, so the token signs exactly that
result and no service accepts it as a credential. The server accepts a check run as the entry's
result only when all of these hold:

1. GitHub's published keys verify the token, and its claims name this repository, one of the entry's
   events, and the entry's workflow file on the default branch as both the run's workflow and the
   job's workflow. A `pull_request` run, a branch's workflow and a reusable workflow all fail here.
2. The marker names this PR and head. Among the results that pass, the newest run decides, so a
   result that a writer posts again does not replace a newer one.
3. The Actions API names the token's `check_run_id`, which is the requesting job's id, as the entry's
   `job` in the token's run. That is the job's name as Actions shows it, not its key in the file. Only
   the jobs that the workflow file grants `id-token: write` can request a token, and this keeps every
   other job of the workflow from publishing, as long as no other job has the same name.

The result lifts something only when the run's own commit holds the same workflow file and pinned
paths as the default branch now, and the marker's `blobs` match them. A re-run of an old run executes
the old code, so its result counts only while that code is still the default branch's.

The token expires five minutes after the job requests it, and a review often comes later, so the
expiry is not checked. The audience binds the token to one result, so an old token proves only what
it signed. Three limits remain:
- A writer's job can edit a newer result's check run and post an older result of the same PR, head
  and merge base again. That result proved the same inputs with code the pins still hold, so this
  matters only for a publisher that can answer differently on the same inputs. The change prover's
  dependency lane can: it reads the npm registry and PyPI, so a pulled release turns a re-run of the
  proof from a success into a neutral, and a writer who hides that neutral brings the success back.
  It takes a job of this repository with `checks: write` and a new review of that head after the
  neutral, and an approval given on the success stands without it.
- A key that GitHub removes from its published set fails every result it signed. The entry then
  waits until the publisher runs again.
- A writer who floods a head with check runs or check suites past GitHub's listing limits keeps the
  entry pending. A flood can delay a lift, never forge one.
"""

import re
import hashlib
from collections.abc import Callable

import jwt
import structlog
from jwt import PyJWK

from posthog.api.oauth.client_assertion import (
    ClientAssertionError,
    JWKSUnavailableError,
    UnknownSigningKeyError,
    select_signing_key,
)
from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.workload_identity.providers import GITHUB_ACTIONS

from products.stamphog.backend.facade.contracts import StamphogGitHubError
from products.stamphog.backend.logic.attestation_pins import (
    MAX_PINNED_PATHS,
    check_runs_with_pins,
    object_marker,
    pin_holds,
)
from products.stamphog.backend.logic.attestation_policy import (
    WORKFLOW_PROOF_KEY,
    WorkflowPublisher,
    workflow_publishers,
)
from products.stamphog.backend.logic.github_client import MAX_CHECK_RUNS, RepositoryIdentity, StamphogGitHubClient

logger = structlog.get_logger(__name__)

# A read that fails proves nothing, so the entry stays pending or lifts nothing. It must not fail the
# review of a PR that the entry may not even cover.
_UNREADABLE = (StamphogGitHubError, GitHubRateLimitError, GitHubEgressBudgetExhausted)
# GitHub lists check runs from only the newest 1000 check suites of a commit
# (https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference).
_LISTED_CHECK_SUITES = 1000
_TOKEN_RE = re.compile(r"<!--\s*stamphog-oidc:v1\s+([A-Za-z0-9_.-]+)\s*-->")
_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
_SHA_RE = re.compile(r"[0-9a-f]{40}")


def proof_audience(check: str, conclusion: str, marker: str) -> str:
    """The audience a publisher requests its token for: a digest of the result it posts.

    `marker` is the marker's JSON exactly as the summary holds it.
    """
    digest = hashlib.sha256(f"stamphog:v1\n{check}\n{conclusion}\n{marker}".encode()).hexdigest()
    return f"stamphog-{digest}"


def _id_claim(claims: dict, key: str) -> int | None:
    """A numeric id claim, which GitHub sends as a string of digits."""
    value = claims.get(key)
    return int(value) if isinstance(value, str) and _ID_RE.fullmatch(value) else None


class _SigningKeyUnavailable(Exception):
    """GitHub's key for a token could not be read, so the token was neither accepted nor refused."""


@frozen(order=True)
class RunOrder:
    """Where a run stands among the publisher's runs: a later run, then a later attempt, comes after."""

    run_id: int
    run_attempt: int


def _claimed_run(token: str) -> RunOrder:
    """The run a token claims, unverified, or the earliest run when it claims none.

    The claims only decide whether to refuse an older result. Nothing unverified is ever accepted.
    """
    try:
        # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return RunOrder(run_id=0, run_attempt=0)
    return RunOrder(run_id=_id_claim(claims, "run_id") or 0, run_attempt=_id_claim(claims, "run_attempt") or 0)


def _github_signing_key(token: str) -> PyJWK:
    """The key that signed the token, from GitHub's key set as the shared JWKS cache holds it."""
    return select_signing_key(GITHUB_ACTIONS.jwks_url, token)


@frozen
class Candidate:
    """A completed check run of the entry's name whose marker names this PR and head."""

    check_run: dict
    marker: str
    payload: dict
    token: str


@frozen
class SignedResult:
    """A candidate whose token verified, with the claims the later checks need."""

    check_run: dict
    run: RunOrder
    job_id: int
    commit_sha: str
    blobs: dict[str, str | None]


class WorkflowProofs:
    """Verifies the signed results of workflow publishers for one PR head."""

    def __init__(
        self,
        client: StamphogGitHubClient,
        repo: str,
        *,
        pr_number: int,
        head_sha: str,
        priority: Priority = Priority.CRITICAL,
        signing_key: Callable[[str], PyJWK] = _github_signing_key,
    ) -> None:
        self._client = client
        self._repo = repo
        self._pr_number = pr_number
        self._head_sha = head_sha
        self._priority = priority
        self._signing_key = signing_key
        self._identity: RepositoryIdentity | None = None

    def _repository_identity(self) -> RepositoryIdentity:
        if self._identity is None:
            self._identity = self._client.get_repository_identity(self._repo, priority=self._priority)
        return self._identity

    def _candidates(self, publisher: WorkflowPublisher) -> list[Candidate]:
        """Each completed check run of the entry's name whose marker names this PR and head, once per token.

        Every check run of the name is read, because GitHub otherwise lists only the newest one, and
        any job can post a newer one to hide the publisher's. The check run ids are a writer's to
        order, so no window of the newest ones is safe: copies of an old result could push a newer one
        out of it. Exact copies of one signed result are verified once. A copy that changed the
        conclusion or the marker is its own candidate, so it cannot take the real one's place.
        """
        check_runs = self._client.get_check_runs(
            self._repo, self._head_sha, check_name=publisher.check, all_runs=True, priority=self._priority
        )
        # Either limit can leave out the newest result while older copies stay listed, so a listing
        # that may have stopped short proves nothing.
        if len(check_runs) >= MAX_CHECK_RUNS:
            raise StamphogGitHubError(f"Too many {publisher.check!r} check runs on {self._head_sha} to verify")
        candidates: dict[tuple[str, object, str], Candidate] = {}
        for check_run in check_runs:
            if check_run.get("name") != publisher.check or check_run.get("status") != "completed":
                continue
            marker = object_marker(check_run)
            if marker is None or marker[1].get("pr") != self._pr_number or marker[1].get("head_sha") != self._head_sha:
                continue
            tokens = _TOKEN_RE.findall((check_run.get("output") or {}).get("summary") or "")
            if len(tokens) != 1:
                continue
            signed_content = (tokens[0], check_run.get("conclusion"), marker[0])
            candidates.setdefault(
                signed_content, Candidate(check_run=check_run, marker=marker[0], payload=marker[1], token=tokens[0])
            )
        if candidates and self._client.count_check_suites(self._repo, self._head_sha, priority=self._priority) > (
            _LISTED_CHECK_SUITES
        ):
            raise StamphogGitHubError(f"Too many check suites on {self._head_sha} to list every check run")
        return list(candidates.values())

    def _decode(self, token: str, audience: str) -> dict | None:
        """The token's claims when GitHub signed it for this audience, or None. The expiry is not checked."""
        try:
            claims = jwt.decode(
                token,
                self._signing_key(token).key,
                algorithms=["RS256"],
                audience=audience,
                issuer=GITHUB_ACTIONS.issuer,
                options={"verify_exp": False, "require": ["iss", "aud", "iat", "exp"]},
            )
        except (JWKSUnavailableError, UnknownSigningKeyError) as error:
            # The token was never checked, so it may be the newest result. `_publisher_result` decides.
            raise _SigningKeyUnavailable from error
        except (ClientAssertionError, jwt.PyJWTError):
            return None
        return claims

    def _names_publisher(self, claims: dict, publisher: WorkflowPublisher) -> bool:
        """True when the claims name the entry's workflow file on the default branch, on one of its events.

        `workflow_ref` names the workflow of the run and `job_workflow_ref` the workflow of the job.
        They differ only for a job of a reusable workflow, which any caller can run with any inputs.
        GitHub documents `job_workflow_ref` for reusable workflows only, but sends it for every job, so
        a token without it names the run's own workflow.
        """
        identity = self._repository_identity()
        expected_ref = f"{identity.full_name}/{publisher.workflow}@refs/heads/{identity.default_branch}"
        workflow_ref = claims.get("workflow_ref")
        return (
            claims.get("repository_id") == str(identity.id)
            and claims.get("event_name") in publisher.events
            and workflow_ref == expected_ref
            and claims.get("job_workflow_ref", workflow_ref) == expected_ref
        )

    def _signed(self, candidate: Candidate, publisher: WorkflowPublisher) -> SignedResult | None:
        conclusion = candidate.check_run.get("conclusion")
        if not isinstance(conclusion, str):
            return None
        claims = self._decode(candidate.token, proof_audience(publisher.check, conclusion, candidate.marker))
        if claims is None or not self._names_publisher(claims, publisher):
            return None
        run_id, run_attempt, job_id = (_id_claim(claims, key) for key in ("run_id", "run_attempt", "check_run_id"))
        commit_sha = claims.get("job_workflow_sha", claims.get("workflow_sha"))
        blobs = candidate.payload.get("blobs", {})
        if run_id is None or run_attempt is None or job_id is None:
            return None
        if not isinstance(commit_sha, str) or not _SHA_RE.fullmatch(commit_sha):
            return None
        if not isinstance(blobs, dict) or not all(sha is None or isinstance(sha, str) for sha in blobs.values()):
            return None
        return SignedResult(
            check_run=candidate.check_run,
            run=RunOrder(run_id=run_id, run_attempt=run_attempt),
            job_id=job_id,
            commit_sha=commit_sha,
            blobs=blobs,
        )

    def _requested_by_publishing_job(self, signed: SignedResult, publisher: WorkflowPublisher) -> bool:
        job = self._client.get_workflow_job(self._repo, signed.job_id, priority=self._priority)
        return job is not None and job.get("name") == publisher.job and job.get("run_id") == signed.run.run_id

    def _publisher_result(self, publisher: WorkflowPublisher) -> SignedResult | None:
        """The newest result that the publishing job signed for this PR and head.

        A token whose key cannot be read is set aside. When its own unchecked claims name a later run
        than the result that would decide, it may be the newest result, so the older one must not
        decide: the publisher is unreadable. A key GitHub removed after an old run leaves that old
        token behind a newer result, where it changes nothing.
        """
        try:
            signed: list[SignedResult] = []
            unchecked: list[RunOrder] = []
            for candidate in self._candidates(publisher):
                try:
                    result = self._signed(candidate, publisher)
                except _SigningKeyUnavailable:
                    unchecked.append(_claimed_run(candidate.token))
                    continue
                if result is not None:
                    signed.append(result)
            for result in sorted(signed, key=lambda result: result.run, reverse=True):
                # A token from another job of the workflow is not the publisher's result, so an older
                # one from the publishing job may still be.
                if not self._requested_by_publishing_job(result, publisher):
                    continue
                if any(run > result.run for run in unchecked):
                    raise StamphogGitHubError(f"A newer {publisher.check!r} result is signed with an unreadable key")
                return result
        except _UNREADABLE:
            logger.warning("stamphog_workflow_proof_unreadable", repo=self._repo, entry=publisher.name)
        return None

    def _code_is_current(self, signed: SignedResult, publisher: WorkflowPublisher) -> bool:
        """True when the run's commit and the default branch hold the same workflow and pinned paths.

        The marker's `blobs` must also match them, so the publisher's account of the code it ran is
        checked rather than taken. A result that pins nothing still pins the workflow file.
        """
        paths = sorted({publisher.workflow, *signed.blobs})
        if len(paths) > MAX_PINNED_PATHS:
            return False
        at_run = self._client.get_objects(self._repo, signed.commit_sha, paths, priority=self._priority)
        now = self._client.get_default_branch_objects(self._repo, paths, priority=self._priority)
        if at_run != now or now.get(publisher.workflow) is None:
            return False
        return all(pin_holds(path, sha, now.get(path)) for path, sha in signed.blobs.items())

    def verified_result(self, publisher: WorkflowPublisher) -> dict | None:
        """The check run the engine reads as the publisher's newest result, or None when there is none."""
        signed = self._publisher_result(publisher)
        if signed is None:
            return None
        conclusion = signed.check_run.get("conclusion")
        code_is_current = False
        # The engine lifts only on a success, so only a success buys the two object reads.
        if conclusion == "success":
            try:
                code_is_current = self._code_is_current(signed, publisher)
            except _UNREADABLE:
                # A stale result would read as completed and refuse the lift for good. With no result
                # the entry stays pending, and the poll reviews again once GitHub answers.
                logger.warning("stamphog_workflow_proof_unreadable", repo=self._repo, entry=publisher.name)
                return None
        return {
            "id": signed.check_run.get("id"),
            "name": publisher.check,
            "app": {"id": None},
            "status": "completed",
            "conclusion": conclusion,
            "output": {"summary": (signed.check_run.get("output") or {}).get("summary") or ""},
            "pinned_blobs_current": code_is_current,
            WORKFLOW_PROOF_KEY: publisher.name,
        }

    def has_result(self, publisher: WorkflowPublisher) -> bool:
        """Whether the engine would find a result for this publisher, which ends its wait.

        The poll asks this before it spends one of the head's few re-reviews, so it runs every check
        the review runs. A result the server cannot finish checking leaves the engine waiting, so it
        must not wake a review either.
        """
        return self.verified_result(publisher) is not None


def proven_check_runs(
    client: StamphogGitHubClient,
    repo: str,
    *,
    pr_number: int,
    head_sha: str,
    check_runs: list[dict],
    policy: str | None,
) -> list[dict]:
    """The head's check runs with each workflow publisher's verified result added, and each App's pins checked.

    Both review paths, the context read and the posting-time gate attestation, build the engine's
    check runs here, so they cannot verify differently.
    """
    proofs = WorkflowProofs(client, repo, pr_number=pr_number, head_sha=head_sha)
    for publisher in workflow_publishers(policy):
        verified = proofs.verified_result(publisher)
        if verified is not None:
            check_runs.append(verified)
    return check_runs_with_pins(client, repo, check_runs)
