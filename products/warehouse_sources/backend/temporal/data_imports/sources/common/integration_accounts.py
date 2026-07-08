import dataclasses


class IntegrationAccountListingError(Exception):
    """Actionable, customer-side failure while listing an integration's accounts (missing config,
    revoked/expired credentials, a deleted integration). The OAuth accounts endpoint maps it to a 400
    so the user gets the message; non-actionable failures stay uncaught and surface as a 500."""


@dataclasses.dataclass(frozen=True)
class IntegrationAccount:
    """A selectable account/resource an OAuth integration exposes (a Bing account, a Search Console
    site, ...). Each platform's client maps its API onto this shape so one frontend selector and one
    serializer cover all of them; platform-specific richness flattens into ``badges`` / ``group``.
    """

    value: str
    """Stored in the source config (numeric account id as a string, site url, etc.)."""
    display_name: str
    is_primary: bool = False
    """Marks the user's own/primary account context. The client (IntegrationAccountSelector) applies the
    ordering — this flag carries no server-side ordering guarantee."""
    badges: tuple[str, ...] = ()
    """Status chips, e.g. ("Active",)."""
    group: str | None = None
    """Grouping for hierarchical platforms (e.g. the owning customer name)."""
    secondary_text: str | None = None
    """Extra searchable identifier shown in parentheses, e.g. the account number."""
