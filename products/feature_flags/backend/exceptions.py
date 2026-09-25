from rest_framework import exceptions


class FlagDependencyConflict(exceptions.ValidationError):
    """Raised when a flag write is refused because of a flag dependency.

    A dedicated type so callers outside the API layer — the scheduled change sweep —
    can tell a deliberate refusal apart from a broken payload without matching on the
    message. It stays a DRF ValidationError, so HTTP callers still get a 400.
    """
