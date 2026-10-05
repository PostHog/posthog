"""Server signature on structured-output records.

Anyone with the project's capture token can send a `$scout_structured_output` event, and a
project member can read run ids and run starts from the scout-runs API. So a reader trusts a
record only when its signature is the server's HMAC over the run id and payload.
"""

import json
from typing import Any

from django.utils.crypto import constant_time_compare, salted_hmac

STRUCTURED_OUTPUT_SIGNATURE_PROPERTY = "record_signature"
_SIGNATURE_SALT = "products.signals.scout_structured_output"


def sign_structured_output(run_id: str, payload: dict[str, Any]) -> str:
    return salted_hmac(_SIGNATURE_SALT, _signed_message(run_id, payload), algorithm="sha256").hexdigest()


def is_signed_structured_output(run_id: str, payload: dict[str, Any], signature: Any) -> bool:
    return isinstance(signature, str) and constant_time_compare(signature, sign_structured_output(run_id, payload))


def _signed_message(run_id: str, payload: dict[str, Any]) -> str:
    return json.dumps([run_id, _normalize_numbers(payload)], sort_keys=True, separators=(",", ":"))


def _normalize_numbers(value: Any) -> Any:
    # Ingestion can re-encode JSON numbers (`1.0` comes back as `1`), so the signature sees every number as a float.
    if isinstance(value, dict):
        return {key: _normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_numbers(item) for item in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return float(value)
        except OverflowError:
            return value
    return value
