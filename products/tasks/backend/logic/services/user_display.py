"""Mapping a core ``User`` onto the display DTO task responses expose.

Its own module so the facade and the services that build their own DTOs share one
implementation: two copies drift, and the drift shows up as an avatar that renders in one
surface and not the other.
"""

from posthog.models.user import User

from products.tasks.backend.facade import contracts


def hedgehog_config(user: User) -> dict | None:
    """Mirror core ``UserBasicSerializer.get_hedgehog_config`` so ``created_by`` output is identical."""
    config = user.hedgehog_config
    if not config:
        return None
    if config.get("version") == 2:
        actor_options = config.get("actor_options", {})
        return {
            "use_as_profile": config.get("use_as_profile"),
            "color": actor_options.get("color"),
            "accessories": actor_options.get("accessories"),
            "skin": actor_options.get("skin"),
        }
    return {
        "use_as_profile": config.get("use_as_profile"),
        "color": config.get("color"),
        "accessories": config.get("accessories"),
        "skin": config.get("skin"),
    }


def user_basic_info(user: User | None) -> contracts.TaskUserBasicInfo | None:
    """Map a core ``User`` to the display DTO (matches ``UserBasicSerializer`` fields)."""
    if user is None:
        return None
    return contracts.TaskUserBasicInfo(
        id=user.id,
        uuid=user.uuid,
        distinct_id=str(user.distinct_id),
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=hedgehog_config(user),
        role_at_organization=user.role_at_organization,
    )
