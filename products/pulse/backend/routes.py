from posthog.api.routing import RouterRegistry

from products.pulse.backend.api import PulseDigestViewSet, PulseFindingViewSet, PulseSubscriptionViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"pulse_digests", PulseDigestViewSet, "environment_pulse_digests", ["team_id"])
    routers.register_legacy_dual_route(
        r"pulse_findings", PulseFindingViewSet, "environment_pulse_findings", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"pulse_subscriptions", PulseSubscriptionViewSet, "environment_pulse_subscriptions", ["team_id"]
    )
