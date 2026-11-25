import re
import json
from dataclasses import replace

import pytest

from change_prover.core.conclusion import DEPENDENCY, REVERT, PublishInputs, conclude

HEAD, MERGE_BASE, WORKFLOW_SHA, BLOB = "a" * 40, "b" * 40, "c" * 40, "d" * 40
RUN_URL = "https://github.com/PostHog/posthog/actions/runs/1"
ATTESTED = PublishInputs(
    head_sha=HEAD,
    workflow_sha=WORKFLOW_SHA,
    details_url=RUN_URL,
    identify_result="success",
    identify_pr="123",
    identify_merge_base=MERGE_BASE,
    identify_eligible="true",
    identify_refused="",
    prove_result="success",
    prove_files='["package.json","pnpm-lock.yaml"]',
    prove_blobs=json.dumps({".nvmrc": BLOB, ".npmrc": None}),
    prove_refused="",
    scan_result="success",
    scan_clean="true",
)
NOT_ELIGIBLE = replace(
    ATTESTED,
    identify_pr="0",
    identify_merge_base="",
    identify_eligible="false",
    prove_result="skipped",
    prove_files="",
    prove_blobs="",
    scan_result="skipped",
    scan_clean="",
)
REFUSED = "The dependency update was refused"
FLAGGED = "The dependency scan flagged an added package"
UNPROVED = "The dependency update could not be proved"


def marker(check_run: dict) -> dict:
    match = re.fullmatch(r"<!-- stamphog:v1 (\{.*\}) -->", check_run["output"]["summary"])
    assert match is not None
    return json.loads(match[1])


def test_an_attested_update_posts_the_check_run_stamphog_reads() -> None:
    decided = conclude(ATTESTED, DEPENDENCY)

    assert decided.check_run == {
        "name": "Dependency proof",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "details_url": RUN_URL,
        "output": {
            "title": "Attested 2 dependency file(s)",
            "summary": '<!-- stamphog:v1 {"files":["package.json","pnpm-lock.yaml"],"blobs":{".nvmrc":"'
            + BLOB
            + '",".npmrc":null},"pr":123,"head_sha":"'
            + HEAD
            + '","merge_base":"'
            + MERGE_BASE
            + '","workflow_sha":"'
            + WORKFLOW_SHA
            + '"} -->',
        },
    }
    assert not decided.unproved


@pytest.mark.parametrize(
    ("inputs", "conclusion", "title", "unproved"),
    [
        (replace(NOT_ELIGIBLE, identify_refused="true"), "neutral", REFUSED, False),
        (replace(ATTESTED, prove_refused="true", prove_files="[]", prove_blobs="{}"), "neutral", REFUSED, False),
        (replace(ATTESTED, scan_clean="false"), "neutral", FLAGGED, False),
        (replace(ATTESTED, prove_refused="true", scan_clean="false"), "neutral", REFUSED, False),
        (NOT_ELIGIBLE, "success", "Nothing to attest", False),
        (replace(ATTESTED, prove_result="failure", prove_files="", prove_blobs=""), "neutral", UNPROVED, True),
        (replace(ATTESTED, scan_result="failure", scan_clean=""), "neutral", UNPROVED, True),
        (replace(ATTESTED, scan_result="cancelled", scan_clean=""), "neutral", UNPROVED, True),
        (
            replace(NOT_ELIGIBLE, identify_result="failure", identify_pr="", identify_eligible=""),
            "neutral",
            UNPROVED,
            True,
        ),
        (replace(ATTESTED, prove_files="[]"), "neutral", UNPROVED, True),
        (replace(ATTESTED, prove_files='["package.json", 1]'), "neutral", UNPROVED, True),
        (replace(ATTESTED, prove_files='{"package.json": null}'), "neutral", UNPROVED, True),
        (replace(ATTESTED, prove_files="not json"), "neutral", UNPROVED, True),
        (replace(ATTESTED, prove_blobs=json.dumps({".nvmrc": BLOB.upper()})), "neutral", UNPROVED, True),
        (replace(ATTESTED, prove_blobs=json.dumps({".nvmrc": 1})), "neutral", UNPROVED, True),
        (replace(ATTESTED, prove_blobs="[]"), "neutral", UNPROVED, True),
        (replace(ATTESTED, prove_blobs=""), "neutral", UNPROVED, True),
    ],
)
def test_the_check_run_conclusion_and_title(inputs: PublishInputs, conclusion: str, title: str, unproved: bool) -> None:
    decided = conclude(inputs, DEPENDENCY)

    assert (decided.check_run["conclusion"], decided.check_run["output"]["title"]) == (conclusion, title)
    assert decided.unproved is unproved
    if conclusion != "success" or title == "Nothing to attest":
        assert (marker(decided.check_run)["files"], marker(decided.check_run)["blobs"]) == ([], {})


@pytest.mark.parametrize(
    ("pr", "merge_base", "expected_pr", "expected_merge_base"),
    [
        ("123", MERGE_BASE, 123, MERGE_BASE),
        ("", "", 0, ""),
        ("123; id", MERGE_BASE.upper(), 0, ""),
        ("-1", MERGE_BASE + "\n", 0, ""),
    ],
)
def test_the_marker_holds_only_a_well_formed_pr_and_merge_base(
    pr: str, merge_base: str, expected_pr: int, expected_merge_base: str
) -> None:
    found = marker(conclude(replace(ATTESTED, identify_pr=pr, identify_merge_base=merge_base), DEPENDENCY).check_run)

    assert (found["pr"], found["merge_base"]) == (expected_pr, expected_merge_base)


REVERT_ATTESTED = replace(ATTESTED, prove_files='["posthog/api/a.py"]', scan_result=None, scan_clean=None)
REVERT_UNPROVED = "The revert could not be proved"


@pytest.mark.parametrize(
    ("inputs", "conclusion", "title", "unproved"),
    [
        (REVERT_ATTESTED, "success", "Attested 1 reverted file(s)", False),
        (
            replace(REVERT_ATTESTED, prove_refused="true", prove_files="[]", prove_blobs="{}"),
            "neutral",
            "The revert was refused",
            False,
        ),
        (
            replace(REVERT_ATTESTED, identify_eligible="false", prove_result="skipped", prove_files="", prove_blobs=""),
            "success",
            "Nothing to attest",
            False,
        ),
        (
            replace(REVERT_ATTESTED, prove_result="failure", prove_files="", prove_blobs=""),
            "neutral",
            REVERT_UNPROVED,
            True,
        ),
        (replace(REVERT_ATTESTED, scan_result="failure"), "neutral", REVERT_UNPROVED, True),
    ],
)
def test_the_revert_lane_posts_its_own_check_without_a_scan(
    inputs: PublishInputs, conclusion: str, title: str, unproved: bool
) -> None:
    decided = conclude(inputs, REVERT)

    assert decided.check_run["name"] == "Revert proof"
    assert (decided.check_run["conclusion"], decided.check_run["output"]["title"]) == (conclusion, title)
    assert decided.unproved is unproved
    attested = title.startswith("Attested")
    assert marker(decided.check_run)["files"] == (["posthog/api/a.py"] if attested else [])
