from products.access_control.backend.facade.user_access_control import UserAccessControlError


class MetricsFeatureGateError(UserAccessControlError):
    """A feature-flag gate refused the run. It stays a UserAccessControlError so existing handlers still catch it,
    but names the flag instead of reporting a role problem the caller cannot fix."""

    def __init__(self, flag: str) -> None:
        super().__init__("metrics", "viewer")
        self.args = (
            f"The `{flag}` feature flag is not enabled for this user or project, so metrics queries cannot run. "
            "This is a feature flag gate, not a role or permission problem.",
        )
