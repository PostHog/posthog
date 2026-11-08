from typing import Any

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from posthog.models.user import User

from .tasks.tasks import delete_fragments_for_user


@receiver(post_delete, sender=User)
def delete_layouts_of_deleted_account(sender: type[User], instance: User, **kwargs: Any) -> None:
    # Layouts live in the product database, so a failure there must not roll back or block the account deletion.
    user_id = instance.id
    transaction.on_commit(lambda: delete_fragments_for_user.delay(user_id))
