from posthog.models.user import User

from products.experiments.backend.facade.contracts import ExperimentCreator


def to_experiment_creator(user: User) -> ExperimentCreator:
    return ExperimentCreator(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )
