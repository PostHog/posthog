from __future__ import annotations

import json
import random
import asyncio
import logging
import argparse
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

from products.posthog_ai.eval_harness.scorers import GRADED_ALIGNMENT_CHOICE_SCORES
from products.workflows.evals.email_cases import CASES, drafting_instructions
from products.workflows.evals.scorers import EMAIL_PROSE_RUBRIC, EmailStructure

MODELS = ("claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5-5")
JUDGE_MODEL = "gpt-6.1-sol"


def parse_cli_result(payload: dict, model: str) -> dict:
    if payload.get("is_error") or payload.get("stop_reason") == "max_tokens":
        raise RuntimeError(f"{model}: generation failed or exhausted its output budget")
    if set(payload.get("modelUsage", {})) != {model}:
        raise RuntimeError(f"{model}: CLI reported a different model; comparison is invalid")
    raw = payload["result"]
    try:
        draft = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except json.JSONDecodeError:
        draft = {}
    emails = draft.get("emails") if isinstance(draft, dict) else None
    if not isinstance(emails, list) or not emails or not all(isinstance(email, dict) for email in emails):
        emails = None
    return {
        "emails": emails,
        "raw_draft": raw,
        "generation_cost_usd": payload["total_cost_usd"],
        "latency_ms": payload["duration_api_ms"],
        "usage": payload["usage"],
        "model_usage": payload["modelUsage"],
    }


class CLIComparison:
    def __init__(self, output_dir: Path, trials: int, instructions: str) -> None:
        self.output_dir = output_dir
        self.trials = trials
        self.instructions = instructions
        self.slots = asyncio.Semaphore(3)

    async def command(self, args: list[str], prompt: str, cwd: str) -> str:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(prompt.encode()), timeout=900)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError(f"{args[0]} failed: {stderr.decode()[-1000:]} {stdout.decode()[-1000:]}")
        return stdout.decode()

    async def generate(self, model: str, case_index: int, trial: int, cwd: str) -> dict:
        case = CASES[case_index]
        async with self.slots:
            raw = await self.command(
                [
                    "claude",
                    "-p",
                    "--model",
                    model,
                    "--effort",
                    "high",
                    "--tools",
                    "",
                    "--strict-mcp-config",
                    "--no-session-persistence",
                    "--system-prompt",
                    self.instructions,
                    "--output-format",
                    "json",
                ],
                case["prompt"],
                cwd,
            )
        payload = json.loads(raw)
        result = {
            "model": model,
            "case": case["name"],
            "trial": trial,
            "brief": case["prompt"],
            **parse_cli_result(payload, model),
        }
        result["structure"] = EmailStructure().eval(output=result, expected=case["expected"]).score
        path = self.output_dir / f"{model}_{case['name']}_{trial}.json"
        path.write_text(json.dumps(result, indent=2))
        logging.info("DONE %s %s trial=%s structure=%s", model, case["name"], trial, result["structure"])
        return result

    async def judge(self, results: list[dict], cwd: str) -> list[dict]:
        blinded = [(index, result) for index, result in enumerate(results) if result["emails"]]
        for result in results:
            if not result["emails"]:
                result["prose"] = 0.0
                result["judge_reason"] = "Missing or malformed email drafts"
        if not blinded:
            return results
        random.Random(73).shuffle(blinded)
        drafts = [
            {
                "id": blind_id,
                "brief": result["brief"],
                "emails": [{k: email.get(k) for k in ("subject", "text")} for email in result["emails"]],
            }
            for blind_id, (_, result) in enumerate(blinded)
        ]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["scores"],
            "properties": {
                "scores": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "grade", "reason"],
                        "properties": {
                            "id": {"type": "integer"},
                            "reason": {"type": "string"},
                            "grade": {"type": "string", "enum": list(GRADED_ALIGNMENT_CHOICE_SCORES)},
                        },
                    },
                }
            },
        }
        schema_path = self.output_dir / "judge-schema.json"
        schema_path.write_text(json.dumps(schema))
        judgment_path = self.output_dir / "judge.json"
        rubric = EMAIL_PROSE_RUBRIC
        prompt = (
            "Grade each independent draft set below. Do not use tools or read files. The model identities are hidden. "
            "Return one grade and a short explanation per id, using the rubric below. Compare no model identities. "
            "Only subject/plain-text prose is under review; structure is scored separately.\n"
            + rubric.replace("{{expected}}", "Each entry supplies its own brief.").replace(
                "{{output}}", "See entries below."
            )
            + "\n"
            + json.dumps(drafts)
        )
        transcript = await self.command(
            [
                "codex",
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--json",
                "--skip-git-repo-check",
                "--model",
                JUDGE_MODEL,
                "--sandbox",
                "read-only",
                "--disable",
                "shell_tool",
                "--disable",
                "unified_exec",
                "--config",
                'model_reasoning_effort="medium"',
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(judgment_path),
                "-",
            ],
            prompt,
            cwd,
        )
        self.output_dir.joinpath("judge-transcript.jsonl").write_text(transcript)
        scores = json.loads(judgment_path.read_text())["scores"]
        if sorted(score["id"] for score in scores) != list(range(len(blinded))):
            raise RuntimeError("Judge omitted or duplicated a draft")
        for score in scores:
            result = results[blinded[score["id"]][0]]
            result["prose"] = GRADED_ALIGNMENT_CHOICE_SCORES[score["grade"]]
            result["judge_reason"] = score["reason"]
        return results

    async def run(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=False)
        with TemporaryDirectory(prefix="workflow-email-eval-") as cwd:
            results = await asyncio.gather(
                *[
                    self.generate(model, case_index, trial, cwd)
                    for trial in range(self.trials)
                    for case_index in range(len(CASES))
                    for model in MODELS
                ]
            )
            results = await self.judge(results, cwd)
        self.output_dir.joinpath("results.json").write_text(json.dumps(results, indent=2))
        grouped: dict[str, list[dict]] = defaultdict(list)
        for result in results:
            grouped[result["model"]].append(result)
        summary = {
            model: {
                "cases": len(rows),
                "prose_mean": mean(row["prose"] for row in rows),
                "structure_mean": mean(row["structure"] for row in rows),
                "cost_mean_usd": mean(row["generation_cost_usd"] for row in rows),
                "latency_mean_ms": mean(row["latency_ms"] for row in rows),
            }
            for model, rows in grouped.items()
        }
        self.output_dir.joinpath("summary.json").write_text(json.dumps(summary, indent=2))
        logging.info("%s\n%s", json.dumps(summary, indent=2), self.output_dir)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("products/posthog_ai/eval_harness/logs/workflow-email-cli")
        / datetime.now(UTC).strftime("%Y%m%d-%H%M%S"),
    )
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    asyncio.run(CLIComparison(args.output_dir.resolve(), args.trials, drafting_instructions()).run())


if __name__ == "__main__":
    main()
