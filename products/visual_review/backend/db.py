from django.conf import settings

_APP_LABEL = "visual_review"
_WRITER_ALIAS = f"{_APP_LABEL}_db_writer"
WRITER_DB: str = _WRITER_ALIAS if _WRITER_ALIAS in settings.DATABASES else "default"
