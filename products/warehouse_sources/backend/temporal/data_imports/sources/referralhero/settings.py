from posthog.dataclasses import frozen

BASE_URL = "https://app.referralhero.com/api/v2/"
API_DOCS_URL = "https://support.referralhero.com/integrate/rest-api/endpoints-reference"


@frozen
class ReferralHeroEndpoint:
    path: str
    data_selector: str
    primary_keys: tuple[str, ...] = ()
    paginated: bool = True


ENDPOINTS: dict[str, ReferralHeroEndpoint] = {
    "lists": ReferralHeroEndpoint(path="lists", data_selector="data.lists", primary_keys=("uuid",)),
    "subscribers": ReferralHeroEndpoint(
        path="lists/{uuid}/subscribers", data_selector="data.subscribers", primary_keys=("list_uuid", "id")
    ),
    "bonuses": ReferralHeroEndpoint(path="lists/{uuid}/bonuses", data_selector="data", paginated=False),
    # Issued rewards have no documented unique key, so full refresh must retain all rows.
    "rewards": ReferralHeroEndpoint(path="lists/{uuid}/rewards", data_selector="data.rewards"),
    "coupon_groups": ReferralHeroEndpoint(
        path="lists/{uuid}/coupon_groups", data_selector="data.coupon_groups", primary_keys=("list_uuid", "id")
    ),
}

AUTH_ERRORS = {
    "code=no_token": "Enter your ReferralHero API token from Account > API.",
    "code=invalid_token": "Your ReferralHero API token is invalid. Copy the token from Account > API.",
    "code=inactive_account": "Your ReferralHero account is inactive. Activate your account before you connect it.",
    "401 Client Error": "Your ReferralHero API token is invalid. Copy the token from Account > API.",
    "403 Client Error": "ReferralHero denied access. Check your account status and API token.",
}
