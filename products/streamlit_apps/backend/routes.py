from posthog.api.routing import RouterRegistry

from products.streamlit_apps.backend.presentation import StreamlitAppViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.environments.register(r"streamlit_apps", StreamlitAppViewSet, "environment_streamlit_apps", ["team_id"])
