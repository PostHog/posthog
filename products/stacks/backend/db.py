from django.conf import settings

_WRITER_ALIAS = "stacks_db_writer"
DATABASE_CONFIGURED: bool = _WRITER_ALIAS in settings.DATABASES
# Every stacks read and write goes to the writer, because a replica can lag behind the lease, the serial and
# the revision that decide whether a mutation may happen. Outside development the alias must exist: falling
# back to the main database there would split the source of truth.
WRITER_DB: str = _WRITER_ALIAS if DATABASE_CONFIGURED else "default"


def database_ready() -> bool:
    return DATABASE_CONFIGURED or settings.DEBUG or settings.TEST
