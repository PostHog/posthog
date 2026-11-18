from uuid import UUID


def parse_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None
