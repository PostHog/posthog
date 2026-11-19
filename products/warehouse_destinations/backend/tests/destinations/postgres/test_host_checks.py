import pytest
from unittest.mock import AsyncMock, patch

from posthog.security.oob_domains import OOB_DOMAIN_REFUSAL

from products.warehouse_destinations.backend.destinations.postgres import client

OOB_DOMAIN = "oob.example.com"


@pytest.mark.parametrize(
    "host, cloud, expected, resolves",
    [
        pytest.param(OOB_DOMAIN, True, OOB_DOMAIN_REFUSAL, False, id="oob-domain-on-cloud"),
        pytest.param(f"db.{OOB_DOMAIN}", True, OOB_DOMAIN_REFUSAL, False, id="oob-subdomain-on-cloud"),
        pytest.param(f"db.{OOB_DOMAIN}", False, None, True, id="oob-subdomain-self-hosted"),
        pytest.param("db.customer.example.org", True, None, True, id="other-domain-on-cloud"),
    ],
)
@pytest.mark.asyncio
async def test_host_check_refuses_out_of_band_domains_before_resolving(
    host: str, cloud: bool, expected: str | None, resolves: bool
) -> None:
    resolve = AsyncMock(return_value=["203.0.113.10"])
    with (
        patch.object(client, "is_cloud", return_value=cloud),
        patch("posthog.security.oob_domains.oob_domains", return_value=frozenset({OOB_DOMAIN})),
        patch.object(client, "_resolve", resolve),
    ):
        detail = await client.host_configuration_error_detail(host, 5432)

    assert detail == expected
    assert resolve.await_count == (1 if resolves else 0)
