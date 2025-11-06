import os
import asyncio
from collections.abc import Sequence
from functools import partial

import pytest

from braintrust import EvalAsync, EvalCase, Metadata, init_logger
from braintrust.framework import EvalData, EvalScorer, EvalTask, Input, Output

from posthog.models.utils import uuid7

from products.enterprise.backend.hogai.eval.schema import DatasetInput


async def _filter_data(data: EvalData[Input, Output], case_filter: str | None = None):
    # Resolve async data
    if asyncio.iscoroutine(data):
        # Async iterator
        if hasattr(data, "__aiter__"):
            data = [case async for case in data]
        # asyncio.iscoroutine may return True for sync generators
        elif hasattr(data, "__iter__"):
            data = list(data)
        # Regular awaitable
        else:
            data = await data
    cases = []
    for case in data:  # type: ignore
        if not isinstance(case, EvalCase):
            cases.append(case)
            continue

        # Reset trace IDs for DatasetInput, so we use distinct IDs instead
        if os.getenv("EVAL_MODE") == "offline" and isinstance(case.input, DatasetInput):
            # Mutating the input in place is intentional here. Just avoiding copying the whole object.
            case.input.trace_id = str(uuid7())

        # Filter by --case <eval_case_name_part> pytest flag
        if case_filter:
            if case_filter in str(case.input):
                cases.append(case)
        else:
            cases.append(case)

    return cases


async def BaseMaxEval(
    experiment_name: str,
    data: EvalData[Input, Output],
    task: EvalTask[Input, Output],
    scores: Sequence[EvalScorer[Input, Output]],
    pytestconfig: pytest.Config,
    metadata: Metadata | None = None,
    is_public: bool = False,
    no_send_logs: bool = True,
):
    if is_public and not no_send_logs:
        # We need to specify a separate project for each MaxEval() suite for comparison to baseline to work
        # That's the way Braintrust folks recommended - Braintrust projects are much more lightweight than PostHog ones
        project_name = f"max-ai-{experiment_name}"
        init_logger(project_name)
    else:
        project_name = experiment_name

    case_filter = pytestconfig.option.eval

    timeout = 60 * 8  # 8 minutes
    if os.getenv("EVAL_MODE") == "offline":
        timeout = 60 * 60  # 1 hour

    result = await EvalAsync(
        project_name,
        data=await _filter_data(data, case_filter=case_filter),
        task=task,
        scores=scores,
        timeout=timeout,
        max_concurrency=100,
        is_public=is_public,
        no_send_logs=no_send_logs,
        metadata=metadata,
    )

    # If we're running in the offline mode and the test case marked as public, the pipeline must completely fail.
    if os.getenv("EVAL_MODE") == "offline" and is_public:
        raise RuntimeError("Evaluation cases must be private when EVAL_MODE is set to offline.")

    if os.getenv("EXPORT_EVAL_RESULTS"):
        with open("eval_results.jsonl", "a") as f:
            f.write(result.summary.as_json() + "\n")

    return result


MaxPublicEval = partial(BaseMaxEval, is_public=True, no_send_logs=False)
"""Evaluation case that is publicly accessible."""

MaxPrivateEval = partial(BaseMaxEval, is_public=False, no_send_logs=True)
"""Evaluation case is not accessible publicly."""
