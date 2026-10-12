import json

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="session")
def service_account_json() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return json.dumps(
        {
            "type": "service_account",
            "client_email": "billing@example-project.iam.gserviceaccount.com",
            "private_key_id": "fake-key-id",
            "private_key": private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
            "token_uri": "https://example.com/untrusted-token-endpoint",
            "universe_domain": "example.com",
        }
    )
