from django.db import migrations

INITIAL_PACKAGES = [
    # Data
    ("numpy", ""),
    ("pandas", ""),
    ("polars", ""),
    ("scipy", ""),
    ("scikit-learn", ""),
    # Visualization
    ("matplotlib", ""),
    ("seaborn", ""),
    ("plotly", ""),
    # Data formats
    ("pyarrow", ""),
    ("duckdb", ""),
    # Web/HTTP
    ("requests", ""),
    ("beautifulsoup4", ""),
    ("lxml", ""),
    # Database
    ("sqlalchemy", ""),
    # Streamlit ecosystem
    ("streamlit", ""),
    ("streamlit-aggrid", ""),
    ("streamlit-extras", ""),
]


def seed_packages(apps, schema_editor):
    AllowedStreamlitPackage = apps.get_model("streamlit_apps", "AllowedStreamlitPackage")
    for name, constraint in INITIAL_PACKAGES:
        AllowedStreamlitPackage.objects.get_or_create(
            name=name,
            defaults={"version_constraint": constraint},
        )


def remove_packages(apps, schema_editor):
    AllowedStreamlitPackage = apps.get_model("streamlit_apps", "AllowedStreamlitPackage")
    names = [name for name, _ in INITIAL_PACKAGES]
    AllowedStreamlitPackage.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("streamlit_apps", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_packages, remove_packages),
    ]
