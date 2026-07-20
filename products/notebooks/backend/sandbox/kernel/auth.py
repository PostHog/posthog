"""Command-token verification — the sandbox side of `sql_v2.mint_command_token`.

Must stay in sync with the HMAC scheme in `products/notebooks/backend/sql_v2.py`;
the mint↔verify round-trip is unit-tested in `test_sql_v2.py`.
"""

import hmac
import time
import hashlib


def verify_command_token(secret: str, run_id: str, token: str) -> bool:
    if not secret or not token:
        return False
    try:
        token_run_id, exp_str, signature = token.rsplit(".", 2)
        exp = int(exp_str)
    except (ValueError, AttributeError):
        return False
    if token_run_id != run_id or exp < int(time.time()):
        return False
    expected = hmac.new(secret.encode(), f"{token_run_id}.{exp_str}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
