from uuid import UUID


def parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None
