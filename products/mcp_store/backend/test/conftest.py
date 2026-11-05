from collections.abc import Iterator

import pytest
from unittest.mock import patch

from posthog.security.url_validation import PinnedUrlVerdict


@pytest.fixture
def pin_oauth_urls() -> Iterator[None]:
    with patch(
        "products.mcp_store.backend.oauth.resolve_mcp_url_policy",
        return_value=PinnedUrlVerdict(allowed=True, reason=None, pinned_ips=set()),
    ):
        yield
