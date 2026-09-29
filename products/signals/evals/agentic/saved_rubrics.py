from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import JsonValue

from products.posthog_ai.eval_harness.scorers.contract import AsyncOnlyScorerMixin, Score, Scorer
from products.signals.backend.rubrics_generation import build_generation_prompt, generate_rubric
from products.signals.backend.rubrics_schema import ScoutRubricCriterion, ScoutRubricSource, default_criteria
from products.signals.backend.scout_harness.prompt import report_disposition_instructions
from products.signals.backend.scout_harness.skill_loader import resolve_report_channel_variant
from products.signals.evals.agentic.rubric_judge import (
    DEFAULT_JUDGE_MODEL,
    DEFAULT_MAX_INPUT_TOKENS,
    PrivateRubricClient,
    RubricJudgment,
    judge_rubric,
)
from products.signals.evals.agentic.rubric_session import RubricSession, RubricSnapshot, SessionRubric, write_judgment

if TYPE_CHECKING:
    from products.signals.evals.agentic.saved_case import SavedScoutInstructions


class SavedRubrics:
    def __init__(
        self,
        saved: SavedScoutInstructions,
        session_dir: Path,
        output_dir: Path,
        *,
        generator_model: str = DEFAULT_JUDGE_MODEL,
        judge_model: str = DEFAULT_JUDGE_MODEL,
        max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
    ) -> None:
        self.saved = saved
        self.session = RubricSession(session_dir)
        self.output_dir = output_dir
        self.generator_model = generator_model
        self.judge_model = judge_model
        self.max_input_tokens = max_input_tokens

    def _canonical_references(self) -> dict[str, JsonValue]:
        skill = self.saved.manifest.skill
        report_channel = resolve_report_channel_variant(skill.allowed_tools)
        return {
            "skill_name": skill.name,
            "skill_version": skill.version,
            "description": skill.description,
            "instructions": skill.body.resolve(self.saved.path.parent).read_text(),
            "allowed_tools": list(skill.allowed_tools),
            "report_channel": report_channel,
            "report_disposition_instructions": report_disposition_instructions(report_channel),
            "reference_files": [
                {
                    "path": file.path,
                    "content_type": file.content_type,
                    "content": file.content.resolve(self.saved.path.parent).read_text(),
                }
                for file in sorted(skill.files, key=lambda item: item.path)
            ],
            "source_cutoff": self.saved.manifest.source_cutoff.isoformat(),
            "time_policy": (
                "These are the fixed reference instructions. Each run may shift saved dates and timestamps; "
                "use its recorded source/target cutoff and investigation bounds when interpreting dates. "
                "Do not substitute a tested variant's changed rules for these reference instructions."
            ),
        }

    async def _generate(self) -> SessionRubric:
        references = self._canonical_references()
        criteria = default_criteria()
        body = str(references["instructions"])
        files = references["reference_files"]
        assert isinstance(files, list)
        snippets: list[JsonValue] = []
        truncated: list[JsonValue] = []
        remaining = 60_000
        for file in files[:4]:
            assert isinstance(file, dict)
            if not remaining:
                break
            content = str(file["content"])
            snippets.append({**file, "content": content[:remaining]})
            if len(content) > remaining:
                truncated.append(file["path"])
            remaining -= len(content[:remaining])
        source_bundle: dict[str, JsonValue] = {
            "scout_context": {
                **{key: value for key, value in references.items() if key not in ("reference_files", "instructions")},
                "instructions": body[:60_000],
                "instructions_truncated": len(body) > 60_000,
                "reference_files": [file.path for file in self.saved.manifest.skill.files[:20]],
                "reference_files_truncated": len(files) > 20,
                "recent_runs": [],
                "saved_criteria": [criterion.model_dump(mode="json") for criterion in criteria],
            },
            "reference_texts": snippets,
            "reference_limits": {"omitted_files": len(files) - len(snippets), "truncated_files": truncated},
            "history_evidence_scope": "No evaluated runs or hidden reference findings are supplied to generation.",
        }

        async def load_criteria() -> list[ScoutRubricCriterion]:
            return criteria

        async with PrivateRubricClient(model=self.generator_model) as client:

            async def send_prompt(prompt: str, phase: str) -> str:
                return await client.ask(prompt)

            try:
                generated = await generate_rubric(
                    build_generation_prompt(source_bundle), send_prompt=send_prompt, load_saved_criteria=load_criteria
                )
            finally:
                self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                attempt = self.output_dir / f"rubric-generation-{uuid4().hex}.json"
                attempt.write_text(json.dumps([call.model_dump(mode="json") for call in client.calls], indent=2) + "\n")
        adopted = [
            *criteria,
            *[
                ScoutRubricCriterion(
                    id=f"custom-{uuid4()}",
                    source=ScoutRubricSource.CUSTOM,
                    enabled=True,
                    **suggestion.model_dump(),
                )
                for suggestion in generated.batch.suggestions
            ],
        ]
        return SessionRubric(
            scout_name=self.saved.skill_name,
            generated_at=datetime.now(UTC),
            criteria=adopted,
            canonical_references=references,
            source=self.saved.metadata,
            generation={
                "generator": generated.model_dump(mode="json"),
                "source_bundle": source_bundle,
                "model": self.generator_model,
                "reasoning_effort": "high",
                "calls": [call.model_dump(mode="json") for call in client.calls],
                "invocation_dir": str(self.output_dir),
                "adoption": "all selected suggestions adopted automatically alongside defaults",
            },
        )

    async def prepare(self) -> RubricSnapshot:
        return await self.session.get_or_create(self.saved.skill_name, self._generate)

    async def judge(
        self,
        output: dict[str, object],
        rubric: RubricSnapshot,
        *,
        source_error: str | None = None,
        source_path: Path | None = None,
        source_sha256: str | None = None,
    ) -> tuple[RubricJudgment, Path]:
        # A previous verdict must not become evidence when the same output is judged again.
        evidence = {key: value for key, value in output.items() if key != "rubric_judgment"}
        async with PrivateRubricClient(model=self.judge_model) as client:
            judgment = await judge_rubric(
                evidence,
                [criterion.model_dump(mode="json") for criterion in rubric.document.criteria],
                rubric.document.canonical_references,
                client.complete,
                max_input_tokens=self.max_input_tokens,
                source_error=source_error,
            )
        payload = judgment.model_dump(mode="json")
        if source_path is not None:
            payload.update(
                source_result_path=str(source_path),
                source_result_sha256=source_sha256,
            )
        path = write_judgment(self.output_dir / "judgments", result=payload, rubric=rubric)
        return judgment, path

    async def judge_saved(self, source_path: Path, rubric: RubricSnapshot) -> tuple[RubricJudgment, Path]:
        content = source_path.read_bytes()
        source = json.loads(content)
        if not isinstance(source, dict) or "output" not in source:
            raise ValueError(f"Expected a saved result.json: {source_path}")
        output = source["output"]
        error = source.get("error")
        if output is None and isinstance(error, str) and error:
            output = {}
        if not isinstance(output, dict) or (error is not None and not isinstance(error, str)):
            raise ValueError(f"Invalid saved result output or execution error: {source_path}")
        metadata = source.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("skill_name") != self.saved.skill_name:
            raise ValueError(f"The saved result does not identify this scout: {source_path}")
        return await self.judge(
            output,
            rubric,
            source_error=error,
            source_path=source_path,
            source_sha256=hashlib.sha256(content).hexdigest(),
        )


class SavedRubricScorer(AsyncOnlyScorerMixin, Scorer):
    def __init__(self, pipeline: SavedRubrics, rubric: RubricSnapshot) -> None:
        self.pipeline = pipeline
        self.rubric = rubric
        self.errors: list[str] = []

    def _name(self) -> str:
        return "scout_rubric"

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        try:
            judgment, path = await self.pipeline.judge(output if isinstance(output, dict) else {}, self.rubric)
        except Exception as error:
            # The engine records scorer exceptions separately from task failures.
            self.errors.append(f"{type(error).__name__}: {error}")
            raise
        if judgment.error:
            self.errors.append(judgment.error)
        scores = [row.score for row in judgment.criteria if row.score is not None]
        complete = not any(row.status in ("unknown", "error") for row in judgment.criteria)
        score = sum(scores) / len(scores) if complete and scores else None
        metadata = {
            "judgment_path": str(path),
            "session_rubric_sha256": self.rubric.sha256,
            "criteria": {row.id: row.status for row in judgment.criteria},
        }
        if isinstance(output, dict):
            output["rubric_judgment"] = metadata
        return Score(name=self._name(), score=score, metadata=metadata)
