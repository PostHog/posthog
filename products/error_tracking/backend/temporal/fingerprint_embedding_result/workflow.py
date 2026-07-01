import json
import hashlib
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.fingerprint_embedding_result.activities import (
        merge_similar_fingerprints_activity,
    )
    from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
        FingerprintEmbeddingMergeResult,
        FingerprintEmbeddingResultInputs,
    )

WORKFLOW_NAME = "error-tracking-fingerprint-embedding-result"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(maximum_attempts=4)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)
ACTIVITY_START_DELAY = timedelta(seconds=30)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingFingerprintEmbeddingResultWorkflow(PostHogWorkflow):
    @staticmethod
    def workflow_id_for(team_id: int, fingerprint: str, rendering: str, timestamp: str) -> str:
        key = f"{fingerprint}:{rendering}:{timestamp}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return f"error-tracking-fingerprint-embedding-result-{team_id}-{digest}"

    @staticmethod
    def parse_inputs(inputs: list[str]) -> FingerprintEmbeddingResultInputs:
        if len(inputs) != 1:
            raise ValueError("Fingerprint embedding result workflow requires exactly one input")
        data = json.loads(inputs[0])
        return FingerprintEmbeddingResultInputs(**data)

    @workflow.run
    async def run(self, inputs: FingerprintEmbeddingResultInputs) -> FingerprintEmbeddingMergeResult:
        if inputs.embedding is None:
            # Older workflow inputs rely on ClickHouse having consumed the embedding row.
            await workflow.sleep(ACTIVITY_START_DELAY)
        return await workflow.execute_activity(
            merge_similar_fingerprints_activity,
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
