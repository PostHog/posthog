from django.db import models

from products.workflows.backend.facade.enums import AdventCalendarDay, AdventCalendarOption


class AdventCalendarAnswer(models.Model):
    user = models.ForeignKey(
        "posthog.User", on_delete=models.DO_NOTHING, db_constraint=False, db_index=False, related_name="+"
    )
    day = models.PositiveSmallIntegerField(choices=AdventCalendarDay.choices)
    option = models.CharField(max_length=16, choices=AdventCalendarOption.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "day"], name="workflows_advent_answer_user_day_unique"),
        ]
