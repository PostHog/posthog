"""Backfill change_kind and ssim_score on existing RunSnapshot rows.

The diff pipeline previously stored two different signals in `diff_percentage`:
true pixel-diff percent for the pixel tier, and SSIM dissimilarity percent
for the SSIM tier (which also zeroed `diff_pixel_count` as a side-effect).
That zeroed-count is the discriminator we use here to repair the semantics.

After this migration:
- Pixel-tier rows: change_kind='pixel', diff_percentage unchanged.
- SSIM-tier rows: change_kind='structural', ssim_score derived from the
  original dissimilarity, diff_percentage NULLed (we don't have the true
  pixel-diff fraction for these rows).
- UNCHANGED rows are left alone — change_kind only applies when CHANGED.
"""

from django.db import migrations
from django.db.models import F, FloatField, Value
from django.db.models.functions import Cast


def backfill_change_kind(apps, _schema_editor):
    RunSnapshot = apps.get_model("visual_review", "RunSnapshot")

    # Pixel tier: classifier saw pixel diff above the 2.5% threshold.
    RunSnapshot.objects.filter(
        result="changed",
        diff_pixel_count__gt=0,
        change_kind="",
    ).update(change_kind="pixel")

    # SSIM tier: pixel diff was below threshold but SSIM dissimilarity
    # cleared the 1% bar. The old code overwrote diff_percentage with
    # `dissimilarity * 100` and zeroed diff_pixel_count — both are how we
    # recognize these rows. Recover ssim_score from the stored dissimilarity
    # and null out the now-misleading diff_percentage. Postgres evaluates all
    # SET expressions against the OLD row, so referencing diff_percentage
    # while also nulling it in the same UPDATE is well-defined.
    RunSnapshot.objects.filter(
        result="changed",
        diff_pixel_count=0,
        diff_percentage__gt=0,
        change_kind="",
    ).update(
        ssim_score=Cast(Value(1.0) - F("diff_percentage") / Value(100.0), output_field=FloatField()),
        diff_percentage=None,
        change_kind="structural",
    )


def reverse(apps, _schema_editor):
    RunSnapshot = apps.get_model("visual_review", "RunSnapshot")

    RunSnapshot.objects.filter(change_kind="pixel").update(change_kind="")

    # Structural rows: rebuild diff_percentage from ssim_score and clear the
    # new fields. Pure SQL again.
    RunSnapshot.objects.filter(
        change_kind="structural",
        ssim_score__isnull=False,
    ).update(
        diff_percentage=Cast((Value(1.0) - F("ssim_score")) * Value(100.0), output_field=FloatField()),
        ssim_score=None,
        change_kind="",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0009_add_ssim_score_and_change_kind"),
    ]

    operations = [
        migrations.RunPython(backfill_change_kind, reverse),
    ]
