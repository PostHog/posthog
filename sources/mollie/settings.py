from dataclasses import dataclass


@dataclass
class MollieEndpointConfig:
    name: str
    path: str
    # Key the rows live under inside the HAL `_embedded` object.
    embedded_key: str
    primary_key: str = "id"
    # Every Mollie resource carries an immutable createdAt.
    partition_key: str = "createdAt"


# No Mollie v2 list endpoint supports created/updated-since filtering — only an
# ID-cursor (`from` + `_links.next`), and mutable objects (payments, refunds,
# chargebacks) change status for days after creation — so every stream is an
# honest full refresh. ID-anchored next links make pagination drift-safe.
MOLLIE_ENDPOINTS: dict[str, MollieEndpointConfig] = {
    "payments": MollieEndpointConfig(
        name="payments",
        path="/payments",
        embedded_key="payments",
    ),
    "refunds": MollieEndpointConfig(
        name="refunds",
        path="/refunds",
        embedded_key="refunds",
    ),
    "chargebacks": MollieEndpointConfig(
        name="chargebacks",
        path="/chargebacks",
        embedded_key="chargebacks",
    ),
    "customers": MollieEndpointConfig(
        name="customers",
        path="/customers",
        embedded_key="customers",
    ),
    "subscriptions": MollieEndpointConfig(
        name="subscriptions",
        path="/subscriptions",
        embedded_key="subscriptions",
    ),
    "settlements": MollieEndpointConfig(
        name="settlements",
        path="/settlements",
        embedded_key="settlements",
    ),
    "payment_links": MollieEndpointConfig(
        name="payment_links",
        path="/payment-links",
        embedded_key="payment_links",
    ),
}

ENDPOINTS = tuple(MOLLIE_ENDPOINTS.keys())
