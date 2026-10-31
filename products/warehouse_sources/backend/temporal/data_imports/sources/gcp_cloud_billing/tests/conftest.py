import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudbilling import (
    GcpCloudBillingKeyFileConfig,
)


@pytest.fixture(scope="session")
def key_file() -> GcpCloudBillingKeyFileConfig:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return GcpCloudBillingKeyFileConfig(
        client_email="billing@example-project.iam.gserviceaccount.com",
        private_key_id="fake-key-id",
        private_key=private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        token_uri="https://example.com/untrusted-token-endpoint",
    )
