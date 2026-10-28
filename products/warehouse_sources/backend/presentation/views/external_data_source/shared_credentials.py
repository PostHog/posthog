"""The API response when a source edit would change credentials that other objects also use."""

from rest_framework import status
from rest_framework.response import Response

from products.warehouse_sources.backend.facade.contracts import UPDATE_SHARED_CREDENTIALS_PARAM, SharedCredentialsError

SHARED_CREDENTIALS_CODE = "shared_credentials"


def shared_credentials_conflict_response(error: SharedCredentialsError) -> Response:
    """A 409 that names the other users of the credentials, so the client can ask for a confirmation.

    The client sends the edit again with `update_shared_credentials=true` to change the credentials
    for every user.
    """
    names = ", ".join(usage.name for usage in error.usages)
    return Response(
        {
            "type": "conflict",
            "code": SHARED_CREDENTIALS_CODE,
            "detail": (
                f"These credentials are also used by {names}. "
                f"Send {UPDATE_SHARED_CREDENTIALS_PARAM}=true to change them everywhere."
            ),
            "attr": None,
            "integration_id": error.integration_id,
            "usages": [{"type": str(usage.type), "id": usage.id, "name": usage.name} for usage in error.usages],
        },
        status=status.HTTP_409_CONFLICT,
    )
