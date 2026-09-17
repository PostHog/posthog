"""Settings for the Django dependency-edge fixture project.

The fixture exists to show, in isolation, what an import graph cannot see about a
Django project. It is not part of the PostHog test suite: `pytest.ini` at the repo
root ignores this directory, and the fixture runs under its own `pytest.ini`.
"""

SECRET_KEY = "fixture-only-not-a-real-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]
USE_TZ = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "shop.apps.ShopConfig",
]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

ROOT_URLCONF = "urls"

MIDDLEWARE: list[str] = []

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# The production behavior a test asserts through the API, changed by settings alone.
SHOP_BULK_DISCOUNT_THRESHOLD = 10
