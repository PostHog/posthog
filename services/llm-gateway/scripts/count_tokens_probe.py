"""Live probe: which Claude models does the bedrock-runtime CountTokens API accept?

Sweeps every model in ANTHROPIC_TO_BEDROCK_MODEL_MAP against the real AWS API with a
one-word message and compares each result with BEDROCK_RUNTIME_COUNT_TOKENS_UNSUPPORTED,
exiting non-zero on any mismatch. Run this before editing the denylist — runtime
CountTokens support is per-model and not derivable from the id shape.

Run from services/llm-gateway with AWS credentials that allow bedrock:CountTokens
(e.g. the llm-gateway role):
    AWS_REGION=us-east-1 .venv/bin/python scripts/count_tokens_probe.py
"""

import json
import sys
from typing import Any

from botocore.exceptions import ClientError

from llm_gateway.bedrock import (
    ANTHROPIC_TO_BEDROCK_MODEL_MAP,
    BEDROCK_ANTHROPIC_VERSION,
    BEDROCK_RUNTIME_COUNT_TOKENS_UNSUPPORTED,
    _strip_regional_inference_prefix,
    get_bedrock_region_name,
    get_bedrock_runtime_client,
)

UNSUPPORTED_MARKER = "doesn't support counting tokens"


def probe(client: Any, model_id: str) -> tuple[bool, str]:
    body = {
        "anthropic_version": BEDROCK_ANTHROPIC_VERSION,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "Hello"}],
    }
    try:
        response = client.count_tokens(
            modelId=model_id,
            input={"invokeModel": {"body": json.dumps(body).encode("utf-8")}},
        )
    except ClientError as exc:
        message = str(exc.response.get("Error", {}).get("Message", exc))
        if UNSUPPORTED_MARKER in message:
            return False, message
        # Any other error (throttling, auth, request validation) is inconclusive — surface it.
        raise
    return True, f"inputTokens={response['inputTokens']}"


def main() -> int:
    region = get_bedrock_region_name()
    if not region:
        print("Set AWS_REGION (and AWS credentials with bedrock:CountTokens) first.")
        return 2
    geo = "eu" if region.startswith("eu-") else "us"
    client = get_bedrock_runtime_client(region, 30.0)

    mismatches: list[str] = []
    probed: set[str] = set()
    for _, region_map in sorted(ANTHROPIC_TO_BEDROCK_MODEL_MAP.items()):
        model_id = _strip_regional_inference_prefix(region_map.get(geo, region_map["us"]))
        if model_id in probed:
            continue
        probed.add(model_id)
        supported, detail = probe(client, model_id)
        expected = model_id not in BEDROCK_RUNTIME_COUNT_TOKENS_UNSUPPORTED
        status = "SUPPORTED" if supported else "unsupported"
        marker = "" if supported == expected else "  << MISMATCH with denylist"
        print(f"{model_id:55} {status:11} {detail}{marker}")
        if supported != expected:
            mismatches.append(model_id)

    if mismatches:
        print(f"\nDenylist out of date for: {', '.join(mismatches)}")
        return 1
    print("\nDenylist matches live CountTokens behavior.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
