from temporalio import activity

from posthog.models import PersonalAPIKey
from posthog.temporal.common.utils import asyncify


@activity.defn
@asyncify
def cleanup_personal_api_key(personal_api_key_id: str) -> None:
    PersonalAPIKey.objects.filter(id=personal_api_key_id).delete()
