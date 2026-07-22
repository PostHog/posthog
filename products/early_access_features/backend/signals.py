from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from products.early_access_features.backend.models import EarlyAccessFeature


@receiver(post_save, sender=EarlyAccessFeature)
def create_waitlist_survey_on_concept_stage(sender, instance: EarlyAccessFeature, **kwargs) -> None:
    """
    When an Early Access Feature is at the `concept` ("Coming Soon") stage and doesn't yet
    have a linked waitlist survey, enqueue a task to create one. The task is gated by the
    `coming-soon-waitlist-surveys` feature flag and is idempotent.

    A signal (rather than a dispatch next to the serializer's stage-change task in api.py)
    is deliberate: it catches every save path — API, Django admin, shell — not just the
    API update flow, so a concept feature can't miss its survey depending on how it was
    edited.

    We enqueue (rather than create inline) because the gate check calls out over the
    network, and we run it `on_commit` so the feature row is durable before the task loads it.
    """
    if instance.stage != EarlyAccessFeature.Stage.CONCEPT:
        return
    if instance.payload and instance.payload.get("survey_id"):
        return

    # Imported lazily to avoid import cycles during app loading.
    from posthog.tasks.early_access_feature import create_waitlist_survey_for_concept_feature

    feature_id = str(instance.id)
    transaction.on_commit(lambda: create_waitlist_survey_for_concept_feature.delay(feature_id))
