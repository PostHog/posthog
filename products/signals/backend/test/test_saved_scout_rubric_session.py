from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from products.signals.backend.rubrics_schema import default_criteria
from products.signals.evals.agentic.rubric_session import RubricSession, SessionRubric


def rubric(scout_name: str = "scout-fixture") -> SessionRubric:
    return SessionRubric(
        scout_name=scout_name,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        criteria=default_criteria(),
        canonical_references={"instructions": "Inspect the fixture and report supported findings."},
        source={"case_id": "fixture"},
        generation={"model": "fixture-model"},
    )


def test_session_reuses_original_rubric_across_concurrent_runs_and_later_commands(tmp_path: Path) -> None:
    async def run() -> None:
        started = asyncio.Event()
        finish = asyncio.Event()
        calls = 0

        async def generate() -> SessionRubric:
            nonlocal calls
            calls += 1
            started.set()
            await finish.wait()
            return rubric()

        first_task = asyncio.create_task(RubricSession(tmp_path).get_or_create("scout-fixture", generate))
        await started.wait()
        later_task = asyncio.create_task(RubricSession(tmp_path).get_or_create("scout-fixture", generate))
        finish.set()
        first, later = await asyncio.gather(first_task, later_task)
        assert calls == 1
        assert first.sha256 == later.sha256

        async def changed_variant() -> SessionRubric:
            raise AssertionError("A different model or prompt must not regenerate the session rubric")

        repeated = await RubricSession(tmp_path).get_or_create("scout-fixture", changed_variant)
        assert repeated.sha256 == first.sha256
        assert repeated.document == first.document
        assert first.path.stat().st_mode & 0o077 == 0

        async def second_scout() -> SessionRubric:
            return rubric("second-scout")

        separate = await RubricSession(tmp_path).get_or_create("second-scout", second_scout)
        assert separate.path != first.path
        assert separate.document.scout_name == "second-scout"

    asyncio.run(run())


@pytest.mark.parametrize("damage", ["edited", "deleted"])
def test_session_rejects_changed_or_missing_pinned_rubric(tmp_path: Path, damage: str) -> None:
    async def run() -> None:
        async def generate() -> SessionRubric:
            return rubric()

        snapshot = await RubricSession(tmp_path).get_or_create("scout-fixture", generate)
        if damage == "deleted":
            snapshot.path.unlink()
        else:
            snapshot.path.write_text(snapshot.path.read_text().replace("fixture-model", "changed-model"))
        with pytest.raises(ValueError, match="pinned session rubric"):
            await RubricSession(tmp_path).get_or_create("scout-fixture", generate)

    asyncio.run(run())


def test_cancelled_generation_releases_session_for_retry(tmp_path: Path) -> None:
    async def run() -> None:
        started = asyncio.Event()

        async def cancelled() -> SessionRubric:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        task = asyncio.create_task(RubricSession(tmp_path).get_or_create("scout-fixture", cancelled))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async def generate() -> SessionRubric:
            return rubric()

        snapshot = await RubricSession(tmp_path).get_or_create("scout-fixture", generate)
        assert snapshot.document.scout_name == "scout-fixture"

    asyncio.run(run())
