"""Lightweight Google Ads config classes.

Kept separate from ``google_ads.py`` so importing the source for registration
(``SourceRegistry`` / ``load_all_sources``) does not drag the ``google-ads`` SDK.
The SDK has a circular module graph that is only safe to import single-threaded;
importing it from concurrent worker threads can deadlock or duplicate-register its
protobuf descriptors. Nothing here imports the SDK — that import is deferred to the
run path in ``source.py``. See ``google_ads.py`` for the SDK-backed functions.
"""

import re
import dataclasses

from products.warehouse_sources.backend.temporal.data_imports.sources.common import config
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig


@dataclasses.dataclass
class GoogleAdsResumeConfig:
    """Resumable state for the Google Ads source.

    `page_token` is the opaque continuation token returned by
    `GoogleAdsService.search` for the next page to fetch.
    """

    page_token: str


def clean_customer_id(s: str | None) -> str | None:
    """Normalize a Google Ads customer ID to its bare digits.

    The Google Ads UI shows customer IDs as ``123-456-7890`` but the API wants the
    bare ``1234567890``. Users paste them with dashes, spaces, or surrounding
    whitespace, so strip everything that isn't a digit — any of those forms then
    works rather than getting rejected at setup time.
    """
    if not s:
        return s

    return re.sub(r"\D", "", s)


def format_customer_id(s: str) -> str:
    """Render a bare 10-digit customer ID the way the Google Ads UI shows it (``123-456-7890``),
    so a picked account matches what the user sees there. Anything else is returned untouched;
    `clean_customer_id` strips the dashes again before the value reaches the API."""
    digits = re.sub(r"\D", "", s)
    if len(digits) != 10:
        return s
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


@config.config
class GoogleAdsServiceAccountSourceConfig(config.Config):
    """Google Ads source config using service account for authentication.

    Old config for when we were using a service account instead of oauth.
    ~100 sources still use this method for auth. We recommend using
    `GoogleAdsSourceConfig` instead"""

    customer_id: str = config.value(converter=clean_customer_id)

    private_key: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY")
    )
    private_key_id: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID")
    )
    client_email: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL")
    )
    token_uri: str = config.value(default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI"))
    developer_token: str = config.value(default_factory=config.default_from_settings("GOOGLE_ADS_DEVELOPER_TOKEN"))


GoogleAdsSourceConfigUnion = GoogleAdsServiceAccountSourceConfig | GoogleAdsSourceConfig
