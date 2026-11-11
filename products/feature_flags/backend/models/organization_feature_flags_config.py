import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode

if TYPE_CHECKING:
    from posthog.models.organization import Organization

logger = logging.getLogger(__name__)


class OrganizationFeatureFlagsConfig(models.Model):
    """Staff-only feature flags settings for an organization.

    An organization without a row reads as FlagEvaluationsMode.EVENTS (mode 0).
    No customer-facing serializer may write this model.
    """

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE
    # lock on posthog_organization (a hot table) while migrating.
    # related_name="+": the relation crosses a product boundary. A cross-product relation must not
    # add a reverse accessor to Organization.
    organization = models.OneToOneField(
        "posthog.Organization", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )

    # The database default keeps raw SQL INSERTs that omit this column valid. Django's default
    # applies only to rows the ORM creates.
    flag_evaluations_mode = models.SmallIntegerField(
        choices=FlagEvaluationsMode.choices,
        default=FlagEvaluationsMode.EVENTS.value,
        db_default=FlagEvaluationsMode.EVENTS.value,
    )

    class Meta:
        # Django checks choices only in full_clean(). ORM saves, QuerySet.update(), and raw SQL writes
        # skip full_clean(). This CHECK makes the database reject any mode that FlagEvaluationsMode
        # does not define. A new mode needs a migration that widens this constraint.
        constraints = [
            models.CheckConstraint(
                name="org_ff_config_flag_evaluations_mode_valid",
                condition=models.Q(flag_evaluations_mode__in=FlagEvaluationsMode.values),
            )
        ]


@receiver(post_save, sender="posthog.Organization")
def create_organization_feature_flags_config(
    sender: type[models.Model], instance: "Organization", created: bool, **kwargs: Any
) -> None:
    """Give a new organization its row at FLAG_EVALUATIONS_NEW_ORG_MODE. A later change to the setting
    does not move an existing organization.

    A failure logs and does not block the organization's creation. The organization then has no row
    and reads as EVENTS.
    """
    if not created:
        return
    mode = settings.FLAG_EVALUATIONS_NEW_ORG_MODE
    if mode not in FlagEvaluationsMode.values:
        # The CHECK constraint rejects a mode that FlagEvaluationsMode does not define.
        logger.warning("Ignoring invalid FLAG_EVALUATIONS_NEW_ORG_MODE %r", mode)
        mode = FlagEvaluationsMode.EVENTS
    try:
        # OrganizationManager.bootstrap creates the organization inside a transaction. get_or_create
        # opens a savepoint, so a failed INSERT rolls back only the savepoint and leaves that
        # transaction usable.
        OrganizationFeatureFlagsConfig.objects.get_or_create(
            organization=instance, defaults={"flag_evaluations_mode": mode}
        )
    except Exception as e:
        logger.warning(f"Error creating OrganizationFeatureFlagsConfig: {e}")
