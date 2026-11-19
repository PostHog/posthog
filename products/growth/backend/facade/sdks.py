from products.growth.backend.constants import SDK_TYPES


def sdk_library_names() -> tuple[str, ...]:
    """The `$lib` values that PostHog's own SDKs send."""
    return tuple(SDK_TYPES)
