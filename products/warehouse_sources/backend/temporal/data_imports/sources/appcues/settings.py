from posthog.dataclasses import frozen

BASE_URLS = {
    "us": "https://api.appcues.com",
    "eu": "https://api.eu.appcues.com",
}


@frozen
class AppcuesEndpoint:
    path: str
    description: str
    docs_anchor: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str = "created_at"


# The list endpoints have no documented timestamp filters or pagination.
# Event exports need a job result field that the public docs do not define.
ENDPOINTS: dict[str, AppcuesEndpoint] = {
    "flows": AppcuesEndpoint(
        path="flows", description="Onboarding flows and their publication settings.", docs_anchor="list-flows"
    ),
    "flows_v2": AppcuesEndpoint(
        path="flows-v2", description="Flows 2.0 and their experience settings.", docs_anchor="list-flows-20"
    ),
    "segments": AppcuesEndpoint(
        path="segments", description="User segments and their creation details.", docs_anchor="list-segments"
    ),
    "tags": AppcuesEndpoint(path="tags", description="Tags used to organize experiences.", docs_anchor="list-tags"),
    "pins": AppcuesEndpoint(
        path="pins", description="Persistent in-app messages and their steps.", docs_anchor="list-pins"
    ),
    "mobile": AppcuesEndpoint(
        path="mobile", description="Mobile experiences and their steps.", docs_anchor="list-mobile-experiences"
    ),
    "launchpads": AppcuesEndpoint(
        path="launchpads", description="Launchpad experiences and their settings.", docs_anchor="list-launchpads"
    ),
    "banners": AppcuesEndpoint(
        path="banners", description="Banner experiences and their settings.", docs_anchor="list-banners"
    ),
    "embeds": AppcuesEndpoint(
        path="embeds", description="Embedded experiences and their settings.", docs_anchor="list-embeds"
    ),
    "nps": AppcuesEndpoint(
        path="nps", description="NPS 2.0 experiences and their settings.", docs_anchor="list-nps-20"
    ),
    "checklists": AppcuesEndpoint(
        path="checklists",
        description="Onboarding checklists and their completion conditions.",
        docs_anchor="list-checklists",
    ),
}
