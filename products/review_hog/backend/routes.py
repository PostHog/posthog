from posthog.api.routing import RouterRegistry

from products.review_hog.backend.api import ReviewHogTriggerViewSet


def register_routes(routers: RouterRegistry) -> None:
    # Unscoped: the trigger resolves team + run user server-side and is gated by a shared secret, so it
    # mounts at /api/review_hog/trigger (no team in the URL) rather than under the project router.
    routers.root.register(r"review_hog", ReviewHogTriggerViewSet, "review_hog")
