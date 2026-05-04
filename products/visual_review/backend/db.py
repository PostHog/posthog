from django.conf import settings

_APP_LABEL = "visual_review"
_WRITER_ALIAS = f"{_APP_LABEL}_db_writer"
_READER_ALIAS = f"{_APP_LABEL}_db_reader"
WRITER_DB: str = _WRITER_ALIAS if _WRITER_ALIAS in settings.DATABASES else "default"
# In tests reads must hit the writer alias — both aliases connect to the same
# physical test DB but run independent transactions, so without this the
# reader can't see writes made earlier in the same test (mirrors the rule in
# `posthog/product_db_router.py`).
READER_DB: str = (
    _WRITER_ALIAS
    if getattr(settings, "TEST", False) and _WRITER_ALIAS in settings.DATABASES
    else (_READER_ALIAS if _READER_ALIAS in settings.DATABASES else "default")
)
