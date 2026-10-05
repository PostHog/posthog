from django.conf import settings

from ..facade.enums import Surface
from ..metrics import ENFORCED_GAUGE

# The surfaces a block rule can refuse. EMAIL_CODE and SIGNUP_RISK only carry exemptions.
ENFORCEABLE_SURFACES = (Surface.SIGNUP, Surface.AI_GATEWAY, Surface.APP)


def is_enforced(surface: Surface) -> bool:
    return surface.value in settings.SECURITY_ACCESS_ENFORCED_SURFACES


def publish_enforcement() -> None:
    """Exposes each surface's switch as a gauge, so a flip can be confirmed per region from Prometheus."""
    for surface in ENFORCEABLE_SURFACES:
        ENFORCED_GAUGE.labels(surface=surface.value).set(1 if is_enforced(surface) else 0)
