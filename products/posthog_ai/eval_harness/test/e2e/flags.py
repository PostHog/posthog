from __future__ import annotations

import json
import threading
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from unittest.mock import patch

from pydantic import BaseModel, ConfigDict, TypeAdapter

Consumer = Literal["browser", "backend", "mcp"]


class Flag(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: bool
    consumers: list[Consumer]


def flag_values(consumer: Consumer) -> dict[str, bool]:
    manifest = TypeAdapter(dict[str, Flag]).validate_json(
        (Path(__file__).resolve().parents[5] / "products/posthog_ai/frontend/e2e/flags.json").read_text()
    )
    return {key: flag.value for key, flag in manifest.items() if consumer in flag.consumers}


def install_flags(stack: ExitStack, output: Path, record_error: Callable[[str], None]) -> None:
    import posthoganalytics
    from posthoganalytics.metrics_capture import PostHogMetrics
    from posthoganalytics.types import FlagsResponse, normalize_flags_response

    values = flag_values("backend")
    lock = threading.Lock()
    consumers: tuple[Consumer, ...] = ("browser", "backend", "mcp")
    (output / "effective-flags.json").write_text(json.dumps({key: flag_values(key) for key in consumers}, indent=2))

    def evaluate(key: str, *args: object, **kwargs: object) -> bool:
        if key not in values and key.startswith(("tasks", "task-", "posthog-ai", "posthog-code", "phai", "max-")):
            record_error(f"Undeclared AI E2E backend flag: {key}")
        value = values.get(key, False)
        with lock, (output / "flag-evaluations.ndjson").open("a") as log:
            log.write(json.dumps({"key": key, "value": value}) + "\n")
        return value

    def decision(*args: object, **kwargs: object) -> FlagsResponse:
        requested = kwargs.get("flag_keys_to_evaluate")
        # The SDK's seventh positional argument is its optional flag-key filter.
        if requested is None and len(args) > 6:
            requested = args[6]
        keys = requested if isinstance(requested, list) else list(values)
        return normalize_flags_response({"featureFlags": {str(key): evaluate(str(key)) for key in keys}})

    def client_evaluate(client: object, key: str, *args: object, **kwargs: object) -> bool:
        return evaluate(key)

    for method in ("feature_enabled", "get_feature_flag"):
        stack.enter_context(patch.object(posthoganalytics, method, evaluate))
        stack.enter_context(patch.object(posthoganalytics.Client, method, client_evaluate))
    for method in ("get_flags_decision", "_get_flags_decision"):
        stack.enter_context(patch.object(posthoganalytics.Client, method, decision))
    stack.enter_context(patch.object(posthoganalytics.Client, "_enqueue", return_value=None))
    stack.enter_context(patch.object(PostHogMetrics, "_capture", return_value=None))
