# Generated migration to remove repository_scope field

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('issue_tracker', '0007_add_repository_scoping'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='issue',
            name='repository_scope',
        ),
    ]