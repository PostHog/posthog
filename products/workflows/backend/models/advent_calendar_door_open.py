from django.db import models


class AdventCalendarDoorOpen(models.Model):
    user = models.ForeignKey(
        "posthog.User", on_delete=models.DO_NOTHING, db_constraint=False, db_index=False, related_name="+"
    )
    day = models.PositiveSmallIntegerField()
    hoggy = models.CharField(max_length=64)
    opened_at = models.DateTimeField(auto_now_add=True)
    utc_offset_minutes = models.SmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "day"], name="workflows_advent_door_open_user_day_unique"),
        ]
