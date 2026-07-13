"""Pure grading for the self-driving eval (see DESIGN.md "Stages & scorers").

This module must stay importable from a bare Python process: no Django, no
Braintrust. It consumes the JSON shape produced by `TaskRunResult.to_json()`
(harness/runner.py) plus the task spec (TASK_SPEC.md) and produces per-scorer
scores with reasoning.
"""

from __future__ import annotations

import os
import re
import json
import shutil
import tempfile
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import anthropic

TASKS_DIR = Path(__file__).resolve().parents[1] / "tasks"

JUDGE_MODEL = "claude-sonnet-4-5"
VERIFY_TIMEOUT_S = 120
NPM_INSTALL_TIMEOUT_S = 180
# Shared across runs so express & co. are only downloaded once per machine.
_NPM_CACHE_DIR = Path(tempfile.gettempdir()) / "signals-selfdriving-npm-cache"

_JUDGE_SYSTEM = (
    "You are a strict evaluator grading one aspect of an autonomous engineering pipeline. "
    'Respond with ONLY a JSON object of the shape {"score": <float 0..1>, "reasoning": "<1-3 sentences>"} '
    "and nothing else - no markdown fences, no prose outside the JSON."
)

JudgeFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def load_task_spec(task_id: str) -> dict[str, Any]:
    return json.loads((TASKS_DIR / task_id / "task.json").read_text())


# ---------------------------------------------------------------------------
# Hidden behavioral tests (DeepSWE-style)
# ---------------------------------------------------------------------------


def _empty_counts() -> dict[str, int]:
    return {"pass": 0, "fail": 0}


def run_verify_suite(task_id: str, repo_dir: Path, patched: bool) -> dict[str, Any]:
    """Run the task's hidden verify/ tests against a scratch copy of repo_dir.

    Returns {"fix": {"pass": n, "fail": m}, "regression": {...}, "raw": "<output tail>"}.
    Fix tests are verify files named test_fix*, regression tests test_regression*.
    """
    verify_src = TASKS_DIR / task_id / "verify"
    result: dict[str, Any] = {"fix": _empty_counts(), "regression": _empty_counts(), "raw": ""}
    if not verify_src.is_dir():
        result["raw"] = f"verify dir missing: {verify_src}"
        return result
    if not repo_dir.is_dir():
        result["raw"] = f"repo dir missing: {repo_dir}"
        return result

    verify_files = sorted(p for p in verify_src.iterdir() if p.is_file() and p.name.startswith("test_"))
    is_python = any(p.suffix == ".py" for p in verify_files)
    fix_files = [p for p in verify_files if p.name.startswith("test_fix")]
    regression_files = [p for p in verify_files if p.name.startswith("test_regression")]

    scratch = Path(tempfile.mkdtemp(prefix=f"verify-{task_id}-{'patched' if patched else 'pristine'}-"))
    raw_parts: list[str] = []
    try:
        work = scratch / "repo"
        shutil.copytree(
            repo_dir, work, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"), symlinks=True
        )
        shutil.copytree(verify_src, work / "verify", dirs_exist_ok=True)
        if is_python:
            result["fix"] = _run_python_group(work, "test_fix*.py", raw_parts)
            result["regression"] = _run_python_group(work, "test_regression*.py", raw_parts)
        else:
            if shutil.which("node") is None:
                result["raw"] = "node not found on PATH"
                return result
            _npm_install(work, raw_parts)
            result["fix"] = _run_node_group(work, fix_files, raw_parts)
            result["regression"] = _run_node_group(work, regression_files, raw_parts)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    result["raw"] = "\n".join(raw_parts)[-8000:]
    return result


def _npm_install(work: Path, raw_parts: list[str]) -> None:
    package_json = work / "package.json"
    if not package_json.is_file():
        return
    try:
        dependencies = json.loads(package_json.read_text()).get("dependencies") or {}
    except json.JSONDecodeError:
        dependencies = {}
    if not dependencies:
        return
    npm = shutil.which("npm")
    if npm is None:
        raw_parts.append("npm not found on PATH; skipping dependency install")
        return
    _NPM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "npm_config_cache": str(_NPM_CACHE_DIR)}
    try:
        proc = subprocess.run(
            [npm, "install", "--no-package-lock", "--omit=dev", "--no-audit", "--no-fund"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=NPM_INSTALL_TIMEOUT_S,
            env=env,
        )
        if proc.returncode != 0:
            raw_parts.append(f"npm install failed:\n{(proc.stdout + proc.stderr)[-2000:]}")
    except subprocess.TimeoutExpired:
        raw_parts.append("npm install timed out")


def _run_node_group(work: Path, files: list[Path], raw_parts: list[str]) -> dict[str, int]:
    if not files:
        return _empty_counts()
    rel_paths = [str(Path("verify") / f.name) for f in files]
    try:
        proc = subprocess.run(
            ["node", "--test", "--test-reporter=tap", *rel_paths],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=VERIFY_TIMEOUT_S,
        )
        output = proc.stdout + "\n" + proc.stderr
    except subprocess.TimeoutExpired as e:
        raw_parts.append(f"node --test timed out after {VERIFY_TIMEOUT_S}s: {_expired_output(e)}")
        return {"pass": 0, "fail": max(len(files), 1)}
    raw_parts.append(output)
    return _parse_tap_summary(output, fallback_fail=len(files))


def _parse_tap_summary(output: str, fallback_fail: int) -> dict[str, int]:
    passed = _tap_count(output, "pass")
    failed = _tap_count(output, "fail")
    cancelled = _tap_count(output, "cancelled") or 0
    if passed is None and failed is None:
        # Crashed before emitting the TAP summary - count the whole group as failing.
        return {"pass": 0, "fail": max(fallback_fail, 1)}
    return {"pass": passed or 0, "fail": (failed or 0) + cancelled}


def _tap_count(output: str, name: str) -> int | None:
    match = re.search(rf"^# {name} (\d+)$", output, re.MULTILINE)
    return int(match.group(1)) if match else None


def _run_python_group(work: Path, pattern: str, raw_parts: list[str]) -> dict[str, int]:
    if not list((work / "verify").glob(pattern)):
        return _empty_counts()
    env = {**os.environ, "PYTHONPATH": str(work)}
    try:
        proc = subprocess.run(
            ["python3", "-m", "unittest", "discover", "-s", "verify", "-p", pattern, "-v"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=VERIFY_TIMEOUT_S,
            env=env,
        )
        output = proc.stdout + "\n" + proc.stderr
    except subprocess.TimeoutExpired as e:
        raw_parts.append(f"unittest timed out after {VERIFY_TIMEOUT_S}s: {_expired_output(e)}")
        return {"pass": 0, "fail": 1}
    raw_parts.append(output)
    ran = re.search(r"Ran (\d+) tests?", output)
    if ran is None:
        return {"pass": 0, "fail": 1}
    total = int(ran.group(1))
    failed = min(sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", output)), total)
    return {"pass": total - failed, "fail": failed}


def _expired_output(e: subprocess.TimeoutExpired) -> str:
    out = e.stdout or b""
    text = out.decode(errors="replace") if isinstance(out, bytes) else out
    return text[-2000:]


def score_behavioral(verify_patched: dict[str, Any], verify_pristine: dict[str, Any]) -> dict[str, Any]:
    fix = verify_patched.get("fix") or _empty_counts()
    regression = verify_patched.get("regression") or _empty_counts()
    pristine_fix = verify_pristine.get("fix") or _empty_counts()
    return {
        "behavioral_correctness": _pass_fraction(fix),
        "no_regressions": _pass_fraction(regression),
        # Sanity: by construction the fix tests must all fail on the unpatched repo.
        "fix_tests_failed_pristine": pristine_fix["fail"] > 0 and pristine_fix["pass"] == 0,
    }


def _pass_fraction(counts: dict[str, int]) -> float:
    total = counts["pass"] + counts["fail"]
    return counts["pass"] / total if total else 0.0


# ---------------------------------------------------------------------------
# LLM judges
# ---------------------------------------------------------------------------


def llm_judge(prompt: str, max_tokens: int = 1200) -> dict[str, Any]:
    """One strict-JSON judge call. Returns {"score": float 0..1, "reasoning": str}."""
    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=max_tokens,
            temperature=0,
            system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        return {"score": 0.0, "reasoning": f"judge call failed: {e}"}
    text = "".join(block.text for block in response.content if block.type == "text")
    return _parse_judge_output(text)


def _parse_judge_output(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start == -1:
        return {"score": 0.0, "reasoning": f"judge output had no JSON: {text[:300]}"}
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return {"score": 0.0, "reasoning": f"judge output unparseable: {text[:300]}"}
    if not isinstance(parsed, dict):
        return {"score": 0.0, "reasoning": f"judge output was not an object: {text[:300]}"}
    try:
        score = float(parsed.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return {"score": min(max(score, 0.0), 1.0), "reasoning": str(parsed.get("reasoning", ""))}


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[... clipped {len(text) - limit} chars]"


def _artefacts_of_type(result: dict[str, Any], *types: str) -> list[dict[str, Any]]:
    return [a for a in result.get("artefacts") or [] if a.get("type") in types]


def _latest_artefact_json(result: dict[str, Any], artefact_type: str) -> dict[str, Any] | None:
    entries = _artefacts_of_type(result, artefact_type)
    if not entries:
        return None
    try:
        content = json.loads(entries[-1].get("content") or "")
    except (json.JSONDecodeError, TypeError):
        return None
    return content if isinstance(content, dict) else None


def _report_section(result: dict[str, Any]) -> str:
    report = result.get("report") or {}
    return "\n".join(
        [
            f"Title: {report.get('title')}",
            f"Summary: {_clip(str(report.get('summary') or ''), 6000)}",
            f"Status: {report.get('status')}",
            f"Priority: {report.get('priority')}",
        ]
    )


def _findings_section(result: dict[str, Any]) -> str:
    findings = _artefacts_of_type(result, "signal_finding", "code_reference", "note")
    if not findings:
        return "(no research findings recorded)"
    return "\n\n".join(f"[{a.get('type')}] {_clip(str(a.get('content') or ''), 4000)}" for a in findings[-20:])


def judge_root_cause(task_spec: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    name = "root_cause_identified"
    if result.get("report") is None:
        return {"name": name, "score": 0.0, "reasoning": "no report was produced"}
    ground_truth = task_spec.get("ground_truth", {})
    prompt = f"""Grade whether an autonomous research pipeline identified the actual planted defect.

<ground_truth>
Root cause: {ground_truth.get("root_cause")}
Culprit files: {json.dumps(ground_truth.get("culprit_files", []))}
</ground_truth>

<candidate_diagnosis>
{_report_section(result)}

Research findings:
{_findings_section(result)}
</candidate_diagnosis>

Scoring rubric:
- 1.0: names the actual defect mechanism AND the right file/surface.
- 0.5: right file/surface but wrong mechanism, or right mechanism but wrong/unspecified file.
- 0.0: wrong diagnosis, or only restates the symptom without a cause.
Intermediate values are allowed for partial matches. Judge the mechanism, not the wording."""
    return {"name": name, **llm_judge(prompt)}


def judge_evidence_grounding(task_spec: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    name = "evidence_grounding"
    if result.get("report") is None:
        return {"name": name, "score": 0.0, "reasoning": "no report was produced"}
    ground_truth = task_spec.get("ground_truth", {})
    prompt = f"""Grade whether the research findings are grounded in the data that actually exists.

<expected_evidence>
{json.dumps(ground_truth.get("expected_evidence", []), indent=2)}
</expected_evidence>

<seeded_event_counts>
{json.dumps(result.get("seeded_counts") or {}, indent=2)}
</seeded_event_counts>

<candidate>
{_report_section(result)}

Research findings:
{_findings_section(result)}
</candidate>

Scoring rubric:
- 1.0: cited evidence is consistent with the expected evidence and seeded counts; numbers and query
  results referenced are plausible against the seeded data.
- Partial credit: surfaces some of the expected evidence, or cites evidence loosely without numbers.
- Penalize heavily (toward 0.0): invented numbers, fabricated query results, or evidence that
  contradicts the seeded data. Not citing a specific count is fine; making one up is not."""
    return {"name": name, **llm_judge(prompt)}


def judge_distractor_avoidance(task_spec: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    name = "distractor_avoidance"
    distractors = task_spec.get("ground_truth", {}).get("distractors") or []
    if not distractors:
        return {"name": name, "score": 1.0, "reasoning": "no distractors planted for this task"}
    if result.get("report") is None:
        return {"name": name, "score": 0.0, "reasoning": "no report was produced"}
    prompt = f"""Grade whether the diagnosis avoids blaming planted red herrings.

<distractors_that_must_not_be_blamed>
{json.dumps(distractors, indent=2)}
</distractors_that_must_not_be_blamed>

<candidate>
{_report_section(result)}

Research findings:
{_findings_section(result)}
</candidate>

Scoring rubric:
- 1.0: none of the distractors is blamed as the cause. Mentioning a distractor and explicitly
  ruling it out is good and still scores 1.0.
- 0.5: a distractor is presented as a plausible contributing cause alongside the real one.
- 0.0: a distractor is blamed as the primary cause."""
    return {"name": name, **llm_judge(prompt)}


def judge_mergeability(task_spec: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    name = "mergeability"
    patch = (result.get("patch") or "").strip()
    if not patch:
        return {"name": name, "score": 0.0, "reasoning": "no patch was produced"}
    ground_truth = task_spec.get("ground_truth", {})
    prompt = f"""You are a senior reviewer deciding whether to merge this change as-is.

<repo_context>
Product: {task_spec.get("product_summary")}
Root cause to fix: {ground_truth.get("root_cause")}
Culprit files: {json.dumps(ground_truth.get("culprit_files", []))}
Fix contract (observable behavior required): {ground_truth.get("fix_contract")}
</repo_context>

<commit_messages>
{json.dumps(result.get("commit_messages") or [], indent=2)}
</commit_messages>

<patch>
{_clip(patch, 30000)}
</patch>

Rubric - would a senior reviewer merge this:
- 1.0: merge as-is. Minimal scoped diff, fixes the root cause (not just the symptom), no debug
  junk or dead code, style consistent with the surrounding code, sensible commits.
- 0.75: merge with nits (minor style issues, slightly broad diff, weak commit messages).
- 0.4: request changes (symptom-level fix, debug leftovers, unrelated edits, sloppy structure).
- 0.0: reject (wrong fix, breaks things, unreviewable dump)."""
    return {"name": name, **llm_judge(prompt)}


def judge_pr_narrative(task_spec: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    name = "pr_narrative"
    implementation_run = result.get("implementation_run") or {}
    commit_messages = result.get("commit_messages") or []
    narrative_artefacts = _artefacts_of_type(result, "task_run", "note", "summary_change")
    if not implementation_run and not commit_messages and not narrative_artefacts:
        return {"name": name, "score": 0.0, "reasoning": "no implementation narrative to grade"}
    artefact_text = (
        "\n\n".join(f"[{a.get('type')}] {_clip(str(a.get('content') or ''), 3000)}" for a in narrative_artefacts[-10:])
        or "(none)"
    )
    prompt = f"""Grade the narrative quality of this autonomous change (its PR-title/description equivalent).

<task_context>
Ground-truth root cause: {task_spec.get("ground_truth", {}).get("root_cause")}
Expected evidence: {json.dumps(task_spec.get("ground_truth", {}).get("expected_evidence", []))}
</task_context>

<narrative>
Implementation run title: {implementation_run.get("title")}
Commit messages: {json.dumps(commit_messages, indent=2)}
PR-description-like artefacts:
{artefact_text}
</narrative>

Scoring rubric (0..1):
- Says WHAT changed and WHY (the defect mechanism, not just "fixed bug").
- References the evidence that motivated the change (errors, event data, customer reports).
- Reads like a mergeable PR a reviewer could evaluate without asking questions.
1.0 = all three clearly; scale down proportionally for what is missing."""
    return {"name": name, **llm_judge(prompt)}


# ---------------------------------------------------------------------------
# Deterministic scorers
# ---------------------------------------------------------------------------


def _score_actionability(task_spec: dict[str, Any], result: dict[str, Any]) -> tuple[float, str]:
    expected = bool(task_spec.get("ground_truth", {}).get("immediately_actionable"))
    judgment = _latest_artefact_json(result, "actionability_judgment")
    if judgment is None or "actionability" not in judgment:
        return 0.0, "no actionability judgment artefact recorded"
    actual = judgment["actionability"] == "immediately_actionable"
    if actual == expected:
        return 1.0, f"assessed {judgment['actionability']!r}, matching ground truth {expected}"
    return 0.0, f"assessed {judgment['actionability']!r}, ground truth immediately_actionable={expected}"


def _priority_grade(value: Any) -> int | None:
    if isinstance(value, str) and re.fullmatch(r"P[0-4]", value):
        return int(value[1])
    return None


def _score_priority(task_spec: dict[str, Any], result: dict[str, Any]) -> tuple[float, str]:
    expected = _priority_grade(task_spec.get("ground_truth", {}).get("priority"))
    if expected is None:
        return 1.0, "task has no ground-truth priority"
    actual_raw = (result.get("report") or {}).get("priority")
    if _priority_grade(actual_raw) is None:
        judgment = _latest_artefact_json(result, "priority_judgment")
        actual_raw = judgment.get("priority") if judgment else None
    actual = _priority_grade(actual_raw)
    if actual is None:
        return 0.0, "no priority was assessed"
    distance = abs(expected - actual)
    score = 1.0 if distance <= 1 else 0.5 if distance == 2 else 0.0
    return score, f"assessed P{actual} vs ground truth P{expected} (distance {distance})"


def _score_pipeline_progression(result: dict[str, Any]) -> tuple[float, str]:
    report = result.get("report")
    if report is None:
        return 0.0, "no report was produced"
    status = report.get("status")
    has_findings = bool(_artefacts_of_type(result, "signal_finding"))
    if status in ("potential", "candidate"):
        return 0.25, f"signals grouped only (report status {status!r})"
    if not has_findings:
        return 0.5, f"report created (status {status!r}) but no research findings"
    if status == "ready":
        return 1.0, "report ready with research findings"
    if status == "pending_input":
        return 0.75, "report pending input after research"
    return 0.5, f"report researched but ended in status {status!r}"


def _score_task_completion(result: dict[str, Any]) -> tuple[float, str]:
    implementation_run = result.get("implementation_run")
    if not implementation_run:
        return 0.0, "no implementation run reached a terminal state"
    status = implementation_run.get("status")
    has_patch = bool((result.get("patch") or "").strip())
    if status == "completed" and has_patch:
        return 1.0, "implementation run completed with a non-empty patch"
    return 0.0, f"implementation run status {status!r}, non-empty patch: {has_patch}"


def _counts_reasoning(counts: dict[str, int], group: str) -> str:
    return f"{counts['pass']}/{counts['pass'] + counts['fail']} {group} tests passing post-patch"


JUDGES: tuple[JudgeFn, ...] = (
    judge_root_cause,
    judge_evidence_grounding,
    judge_distractor_avoidance,
    judge_mergeability,
    judge_pr_narrative,
)


def grade_result(task_spec: dict[str, Any], result: dict[str, Any], repos_workspace: Path) -> dict[str, Any]:
    """Grade one TaskRunResult JSON. Returns {scorer_name: {"score", "reasoning"}, "meta": {...}}.

    The patched working copy IS the mounted repo the agent committed into
    (repos_workspace/<task_id>); it is graded directly. The pristine baseline
    is the task's template repo.
    """
    task_id = task_spec["task_id"]
    pristine_repo = TASKS_DIR / task_id / "repo"
    patched_repo = repos_workspace / task_id
    if not patched_repo.is_dir() and (repos_workspace / "repos" / task_id).is_dir():
        patched_repo = repos_workspace / "repos" / task_id

    with ThreadPoolExecutor(max_workers=len(JUDGES) + 2) as pool:
        pristine_future = pool.submit(run_verify_suite, task_id, pristine_repo, False)
        patched_future = pool.submit(run_verify_suite, task_id, patched_repo, True)
        judge_futures = [pool.submit(judge, task_spec, result) for judge in JUDGES]
        verify_pristine = pristine_future.result()
        verify_patched = patched_future.result()
        verdicts = [future.result() for future in judge_futures]

    behavioral = score_behavioral(verify_patched, verify_pristine)
    scores: dict[str, Any] = {
        verdict["name"]: {"score": verdict["score"], "reasoning": verdict["reasoning"]} for verdict in verdicts
    }
    scores["behavioral_correctness"] = {
        "score": behavioral["behavioral_correctness"],
        "reasoning": _counts_reasoning(verify_patched["fix"], "fix"),
    }
    scores["no_regressions"] = {
        "score": behavioral["no_regressions"],
        "reasoning": _counts_reasoning(verify_patched["regression"], "regression"),
    }
    for scorer_name, (score, reasoning) in {
        "actionability_calibration": _score_actionability(task_spec, result),
        "priority_calibration": _score_priority(task_spec, result),
        "pipeline_progression": _score_pipeline_progression(result),
        "task_completion": _score_task_completion(result),
    }.items():
        scores[scorer_name] = {"score": score, "reasoning": reasoning}

    # FrontierSWE-style gated score: a lucky patch without a correct diagnosis caps at 0.5.
    root_cause_score = scores["root_cause_identified"]["score"]
    behavioral_score = behavioral["behavioral_correctness"]
    scores["e2e_resolution"] = {
        "score": behavioral_score * (0.5 + 0.5 * root_cause_score),
        "reasoning": f"behavioral {behavioral_score:.2f} gated on root cause {root_cause_score:.2f}",
    }
    scores["meta"] = {
        "verify_pristine": verify_pristine,
        "verify_patched": verify_patched,
        "fix_tests_failed_pristine": behavioral["fix_tests_failed_pristine"],
        "pristine_repo": str(pristine_repo),
        "patched_repo": str(patched_repo),
    }
    return scores
