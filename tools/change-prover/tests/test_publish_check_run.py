import json
import shutil
import hashlib
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "publish-check-run.sh"
HEAD = "a" * 40
MERGE_BASE = "b" * 40
TOKEN = "header.payload.signature"


def stamphog_audience(check: str, conclusion: str, marker: str) -> str:
    # stamphog's `proof_audience` in products/stamphog/backend/logic/workflow_proofs.py. A drift on either
    # side leaves every proof unsigned in stamphog's eyes, so the entry waits forever.
    return "stamphog-" + hashlib.sha256(f"stamphog:v1\n{check}\n{conclusion}\n{marker}".encode()).hexdigest()


def decided_check_run() -> str:
    marker = json.dumps(
        {"files": ["pnpm-lock.yaml"], "blobs": {}, "pr": 7, "head_sha": HEAD, "merge_base": MERGE_BASE},
        separators=(",", ":"),
    )
    return json.dumps(
        {
            "name": "Dependency proof",
            "head_sha": HEAD,
            "status": "completed",
            "conclusion": "success",
            "output": {"title": "Attested 1 dependency file(s)", "summary": f"<!-- stamphog:v1 {marker} -->"},
        }
    )


def run_script(tmp_path: Path, check_run: str, *, token_service_up: bool = True) -> tuple[int, str, dict]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # The fakes record what crosses the boundary: the token request URL and the posted check run.
    (bin_dir / "curl").write_text(
        f'#!/usr/bin/env bash\necho "${{@: -1}}" > "{tmp_path}/token_url"\n'
        + (f'echo \'{{"value": "{TOKEN}"}}\'\n' if token_service_up else "exit 22\n")
    )
    (bin_dir / "gh").write_text(f'#!/usr/bin/env bash\ncat > "{tmp_path}/posted"\n')
    for fake in ("curl", "gh"):
        (bin_dir / fake).chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{Path(shutil.which('jq')).parent}:{Path(shutil.which('sha256sum')).parent}:/usr/bin:/bin",
        "CHECK_NAME": "Dependency proof",
        "CHECK_RUN": check_run,
        "HEAD_SHA": HEAD,
        "WORKFLOW_SHA": "c" * 40,
        "IDENTIFY_PR": "7",
        "IDENTIFY_MERGE_BASE": MERGE_BASE,
        "REPOSITORY": "PostHog/posthog",
        "GH_TOKEN": "unused",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example.com/request?api-version=2.0",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "unused",
    }
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)
    token_url = (tmp_path / "token_url").read_text().strip()
    return result.returncode, token_url, json.loads((tmp_path / "posted").read_text())


@pytest.mark.skipif(not (shutil.which("jq") and shutil.which("sha256sum")), reason="needs jq and sha256sum")
@pytest.mark.parametrize(
    "check_run, token_service_up, expected_status, expected_conclusion, signed",
    [
        pytest.param(decided_check_run(), True, 0, "success", True, id="decided"),
        # `conclude` broke, so the neutral check still names the PR and head, and the run fails.
        pytest.param("", True, 1, "neutral", True, id="conclude-broke"),
        pytest.param(decided_check_run(), False, 1, "success", False, id="no-token"),
    ],
)
def test_the_posted_check_run_carries_a_token_for_exactly_its_own_result(
    tmp_path: Path,
    check_run: str,
    token_service_up: bool,
    expected_status: int,
    expected_conclusion: str,
    signed: bool,
) -> None:
    status, token_url, posted = run_script(tmp_path, check_run, token_service_up=token_service_up)

    marker_text, _, token_line = posted["output"]["summary"].partition("\n")
    marker = marker_text.removeprefix("<!-- stamphog:v1 ").removesuffix(" -->")
    assert status == expected_status
    assert posted["conclusion"] == expected_conclusion
    assert (json.loads(marker)["pr"], json.loads(marker)["head_sha"]) == (7, HEAD)
    assert token_url.endswith("&audience=" + stamphog_audience("Dependency proof", expected_conclusion, marker))
    assert token_line == (f"<!-- stamphog-oidc:v1 {TOKEN} -->" if signed else "")
