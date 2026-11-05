import json

from products.posthog_ai.eval_harness.harness.generation_capture import parse_generation


def test_parse_generation_keeps_tier_and_usage_and_drops_bodies():
    boundary = "b0undary"
    event = {"uuid": "u-1", "event": "$ai_generation", "distinct_id": "user-1", "timestamp": "2026-01-01T00:00:00Z"}
    properties = {
        "$ai_service_tier": "flex",
        "$ai_service_tier_requested": "flex",
        "$ai_cache_read_input_tokens": 1200,
        "$ai_input": [{"role": "user", "content": "x" * 50}],
        "$ai_output_choices": [{"role": "assistant", "content": "y"}],
    }
    body = (
        "".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\nContent-Type: application/json\r\n\r\n'
            f"{json.dumps(part)}\r\n"
            for name, part in (("event", event), ("event.properties", properties))
        )
        + f"--{boundary}--\r\n"
    )

    record = parse_generation(f"multipart/form-data; boundary={boundary}", body.encode())

    assert record == {
        **event,
        "properties": {
            "$ai_service_tier": "flex",
            "$ai_service_tier_requested": "flex",
            "$ai_cache_read_input_tokens": 1200,
        },
    }
