"""Shared helpers for feature flag write tests. This module is not a test module itself."""

from typing import TYPE_CHECKING

from rest_framework.test import APIClient

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

# Each mode turns a flag on without sending new targeting. The serializer must then check the stored filters.
# "restore" expects a soft-deleted flag stored with active=True. The other modes expect a disabled flag.
TURN_ON_MODES = ("patch", "empty", "action", "restore")


def turn_flag_on(client: APIClient, flag_url: str, mode: str) -> "_MonkeyPatchedResponse":
    if mode == "action":
        return client.post(f"{flag_url}enable/", {}, format="json")
    if mode == "restore":
        return client.patch(flag_url, {"deleted": False}, format="json")
    if mode == "empty":
        return client.patch(flag_url, {"active": True, "filters": {}}, format="json")
    return client.patch(flag_url, {"active": True}, format="json")
