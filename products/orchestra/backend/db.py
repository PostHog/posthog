from django.conf import settings

_APP_LABEL = "orchestra"
_WRITER_ALIAS = f"{_APP_LABEL}_db_writer"
_READER_ALIAS = f"{_APP_LABEL}_db_reader"
WRITER_DB: str = _WRITER_ALIAS if _WRITER_ALIAS in settings.DATABASES else "default"
READER_DB: str = (
    _WRITER_ALIAS
    if getattr(settings, "TEST", False) and _WRITER_ALIAS in settings.DATABASES
    else (_READER_ALIAS if _READER_ALIAS in settings.DATABASES else "default")
)
