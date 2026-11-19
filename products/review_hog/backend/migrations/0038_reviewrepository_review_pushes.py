from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("review_hog", "0037_reviewrepository_deep_review_gated_prs"),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewrepository",
            name="review_pushes",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
