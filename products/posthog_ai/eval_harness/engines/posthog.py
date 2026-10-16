from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

from .braintrust import BraintrustEngine
from .types import EnvVarSpec, ExperimentResult, ExperimentSpec


class PostHogEngine(BraintrustEngine):
    name: ClassVar[str] = "posthog"
    supports_public_experiments: ClassVar[bool] = False

    @classmethod
    def required_env(cls) -> tuple[EnvVarSpec, ...]:
        return (EnvVarSpec("POSTHOG_OFFLINE_EVAL_API_KEY", "publishes offline evaluation results to PostHog"),)

    async def run_experiment(self, spec: ExperimentSpec) -> ExperimentResult:
        # Use the same local evaluator and scorer semantics, but never contact Braintrust.
        # The run's finalizer publishes to PostHog using the suite's original upload policy.
        return await super().run_experiment(replace(spec, no_send_logs=True, is_public=False))
