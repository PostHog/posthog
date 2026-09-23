"""Messaging providers (SES, Twilio, maildev).

PEP 562 shim: the provider modules pull vendor SDKs (boto3/botocore, dnspython) at import, and
`posthog.models.integration` reaches this package during django.setup(). Public names resolve
lazily on first attribute access; submodule imports (`from .ses import SESProvider`) do not run
the aggregation. Only names in `__all__` are served, so `from package import submodule` still
falls back to normal module resolution.
"""

import importlib

__all__ = ["TwilioProvider", "SESProvider", "MAILDEV_MOCK_DNS_RECORDS"]

_LOCATIONS = {
    "MAILDEV_MOCK_DNS_RECORDS": ".maildev",
    "SESProvider": ".ses",
    "TwilioProvider": ".twilio",
}


def __getattr__(name: str):
    if name in _LOCATIONS:
        module = importlib.import_module(_LOCATIONS[name], __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
