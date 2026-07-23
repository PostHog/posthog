"""Payloads for test-health reads and the quarantine sidecar."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    BrokenTestRow,
    BrokenTestsResult,
    FlakyTestItem,
    FlakyTestList,
    QuarantineEntry,
    QuarantineFile,
    QuarantineRequest,
    QuarantineRequestResult,
)
from products.engineering_analytics.backend.presentation.serializers._shared import RepoRefSerializer


class FlakyTestItemSerializer(DataclassSerializer):
    class Meta:
        dataclass = FlakyTestItem
        extra_kwargs = {
            "nodeid": {
                "help_text": "Reconstructed pytest nodeid (the CI span name), e.g. "
                "'posthog/api/test/test_event/TestEvents::test_x'. A stable grouping key, not a runnable "
                "selector — use `selector` to run or quarantine the test.",
            },
            "selector": {
                "help_text": "Runnable pytest selector, e.g. "
                "'posthog/api/test/test_event.py::TestEvents::test_x'. Exact when the CI reporter emitted it; "
                "otherwise reconstructed from the nodeid, where the file/class boundary is a best-effort guess.",
            },
            "classification": {
                "help_text": "confirmed_flake: an in-job retry recovered the test in the same run, so it is "
                "provably nondeterministic. quarantined: it fails while masked as xfail. suspected_regression: "
                "only failures were recorded, which is absence of proof, not proof that it is a real break.",
            },
            "rerun_passed_run_count": {
                "help_text": "Runs where an in-job pytest retry recovered the test after it failed. Above zero is "
                "the only proof of flakiness this data carries, and it reaches only tests hand-marked "
                "@pytest.mark.flaky(reruns=N), since Backend CI runs without --reruns so failures stay visible.",
            },
            "failed_run_count": {
                "help_text": "Distinct CI runs whose recorded outcome was failed or error. A run counts once "
                "however many matrix legs it failed in.",
            },
            "failed_pr_count": {
                "help_text": "Distinct pull requests among the failed runs. Failures on master or unattributed "
                "branches carry no PR number and are excluded here (still in failed_run_count).",
            },
            "master_failed_run_count": {
                "help_text": "Failed runs on the default branch (master/main approximation): the 'matters right "
                "now' signal that a test is breaking the trunk, not just PR branches.",
            },
            "quarantined_failed_run_count": {
                "help_text": "Runs where the test failed while quarantined (xfail): already masked in CI, still "
                "failing.",
            },
            "last_signal_at": {
                "help_text": "Most recent failure, recovery, or xfail run for this test in the window.",
            },
        }


class FlakyTestListSerializer(DataclassSerializer):
    items = FlakyTestItemSerializer(
        many=True,
        help_text="Tests worth acting on now, ranked by blast radius: master failures, then PRs hit, then runs.",
    )

    class Meta:
        dataclass = FlakyTestList
        extra_kwargs = {
            "truncated": {
                "help_text": "True when more tests qualified than the cap; `items` is the highest-ranked `limit` rows.",
            },
            "limit": {"help_text": "Maximum number of tests returned in `items`."},
        }


class BrokenTestRowSerializer(DataclassSerializer):
    class Meta:
        dataclass = BrokenTestRow
        extra_kwargs = {
            "fingerprint": {
                "help_text": "Stable identity of this distinct failure: the failing test's node id plus a "
                "normalized error signature, so the same failure across runs groups into one row.",
            },
            "test_id": {"help_text": "The pytest node id from the CI 'FAILED <id>' line — the failing test."},
            "error_signature": {
                "help_text": "The trailing failure detail with volatile bits (numbers, hashes) normalized, shared "
                "across runs of the same failure. Empty when the FAILED line carried no detail.",
            },
            "job_name": {
                "help_text": "The CI job the failure most recently came from. Matched against default-branch job "
                "status to decide whether trunk is currently broken by it.",
            },
            "repo": {"help_text": "'owner/name' repository the failure belongs to."},
            "state": {
                "help_text": "The classifier's verdict on how this failure is behaving right now: "
                "'breaking_master' (failing on trunk, latest trunk run still red), 'novel_burst' (new within a "
                "day and spreading across branches, not on trunk yet), 'potentially_resolved' (hit trunk but "
                "trunk is green again), 'flaky' (sporadic across branches over more than a day), or 'pr_only' "
                "(confined to one branch — one PR's own problem).",
            },
            "first_seen": {"help_text": "Earliest failure line for this fingerprint in the analysis window."},
            "last_seen": {"help_text": "Most recent failure line for this fingerprint in the analysis window."},
            "occurrences": {
                "help_text": "Total failure lines for this fingerprint in the window. An absolute count, never a "
                "rate — passing runs aren't in this data.",
            },
            "branches": {"help_text": "Distinct branches the failure appeared on in the window."},
            "master_hits": {
                "help_text": "Failure lines on the default branch (master/main). 0 means it never reached trunk.",
            },
            "latest_run_id": {
                "help_text": "The most recent failing workflow run for this fingerprint — pass it to "
                "run_failure_logs to fetch the actual failing log lines.",
            },
            "latest_branch": {"help_text": "The branch of the most recent failing run."},
            "trend_24h": {
                "help_text": "Hourly failure counts over the last 24 hours, oldest first (fixed 24-slot array), "
                "for the row sparkline. All zeros when nothing failed in the last day.",
            },
        }


class BrokenTestsResultSerializer(DataclassSerializer):
    rows = BrokenTestRowSerializer(
        many=True,
        help_text="Classified failures ranked by triage urgency — breaking trunk first, single-PR failures last.",
    )

    class Meta:
        dataclass = BrokenTestsResult
        extra_kwargs = {
            "breaking_master_jobs": {
                "help_text": "Default-branch job names whose latest completed run is failing — the 'what's on fire "
                "right now' summary. Empty when the job-level source isn't synced or trunk is green.",
            },
            "window_days": {"help_text": "Length in days of the analysis window the counts cover."},
            "truncated": {
                "help_text": "True when more failures qualified than the cap; `rows` is the top `limit` by urgency.",
            },
            "limit": {"help_text": "Maximum number of rows returned."},
        }


class QuarantineEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = QuarantineEntry
        extra_kwargs = {
            "id": {
                "help_text": "Test selector: an exact test id, a file, a directory, a class prefix, or "
                "'product:<dashed-name>'.",
            },
            "runner": {"help_text": "Test runner the selector targets, e.g. 'pytest' or 'jest'."},
            "reason": {"help_text": "Why the test was quarantined."},
            "owner": {"help_text": "GitHub team or user handle responsible for the fix."},
            "issue": {"help_text": "Tracking issue URL, or empty when none was filed."},
            "added": {"help_text": "ISO date the entry was added."},
            "expires": {"help_text": "ISO date the quarantine expires; past it the test blocks CI normally again."},
            "mode": {
                "help_text": "'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all).",
            },
            "lifecycle": {
                "help_text": "Expiry classification: 'active' (>7 days left), 'expiring_soon' (0-7 days left), "
                "'in_grace' (expired up to 7 days ago), 'overdue' (expired beyond the grace period).",
            },
            "days_until_expiry": {"help_text": "Days until the entry expires; negative once past expiry."},
            "selector_kind": {
                "help_text": "What the selector covers: 'test' (contains '::'), 'file', 'directory', or 'product'.",
            },
        }


class QuarantineFileSerializer(DataclassSerializer):
    entries = QuarantineEntrySerializer(
        many=True,
        help_text="Quarantined selectors, most urgent first (overdue, in_grace, expiring_soon, active), "
        "then by soonest expiry.",
    )
    repo = RepoRefSerializer(
        help_text="Repository the file was read from. Null in local-dev mode, where the server's own checkout is read.",
        allow_null=True,
    )

    class Meta:
        dataclass = QuarantineFile
        extra_kwargs = {
            "available": {
                "help_text": "False when the repository has no quarantine file (not an error) or it could not "
                "be fetched.",
            },
            "parse_errors": {
                "help_text": "Contract violations (malformed JSON, bad entries) or fetch failures. Malformed "
                "entries are dropped; well-formed ones are kept.",
            },
            "parse_warnings": {"help_text": "Forward-compatibility notices, e.g. unknown entry fields."},
            "source_url": {
                "help_text": "GitHub blob URL of the quarantine file, or empty when read locally or unavailable.",
            },
            "generated_at": {"help_text": "When this snapshot was computed (UTC); expiry math uses this clock."},
        }


class QuarantineRequestSerializer(DataclassSerializer):
    class Meta:
        dataclass = QuarantineRequest
        extra_kwargs = {
            "operation": {
                "help_text": "What to do: 'quarantine' (add or replace an entry and file a tracking issue), 'extend' "
                "(re-stamp an existing entry's expiry, reusing its issue), or 'remove' (delete the entry). All three "
                "open a pull request.",
            },
            "selector": {
                "help_text": "Test selector to act on: an exact test id, a file, a directory, a class prefix, or "
                "'product:<dashed-name>'.",
            },
            "repo": {
                "help_text": "Optional 'owner/name' repository override; defaults to the team's most active repo.",
                "allow_null": True,
                "required": False,
            },
            # Blank is meaningful: remove sends no reason/owner, and quarantine sends no issue
            # (the server files one). Per-action required checks live in the logic layer.
            "reason": {
                "help_text": "Why the test is quarantined. Required for quarantine and extend; ignored by remove.",
                "required": False,
                "allow_blank": True,
            },
            "owner": {
                "help_text": "GitHub team or user handle responsible for the fix, e.g. '@PostHog/team-x'. Required "
                "for quarantine and extend.",
                "required": False,
                "allow_blank": True,
            },
            "issue": {
                "help_text": "Existing tracking issue URL, carried forward on extend and remove. Ignored by "
                "quarantine, which files a fresh issue.",
                "required": False,
                "allow_blank": True,
            },
            "expires": {
                "help_text": "ISO date the quarantine expires (at most 30 days out). Defaults to 14 days from today. "
                "Ignored by remove.",
                "allow_null": True,
                "required": False,
            },
            "mode": {
                "help_text": "'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all). "
                "Defaults to 'run'.",
                "required": False,
            },
        }


class QuarantineRequestResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = QuarantineRequestResult
        extra_kwargs = {
            "pr_url": {"help_text": "URL of the opened pull request that edits the quarantine file."},
            "issue_url": {
                "help_text": "URL of the tracking issue filed for a new quarantine; empty for extend and remove.",
            },
            "branch": {"help_text": "Branch the pull request was opened from."},
        }
