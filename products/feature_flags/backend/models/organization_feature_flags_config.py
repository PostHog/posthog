from django.db import models

from products.feature_flags.backend.models.team_feature_flags_config import FlagEvaluationsMode


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
        choices=FlagEvaluationsMode,
        default=FlagEvaluationsMode.EVENTS,
        db_default=FlagEvaluationsMode.EVENTS,
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
