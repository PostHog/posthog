"""Uploaded recipient lists: a batch audience that brings its own rows and per-recipient variables."""

from products.workflows.backend.services.recipient_lists import (
    MAX_RECIPIENT_LIST_ROWS,
    RECIPIENT_LIST_AUDIENCE_TYPE,
    RecipientListInvalid,
    RecipientListNotFound,
    create_recipient_list,
    get_recipient_list,
    get_recipient_list_page,
    is_recipient_list_audience,
)

__all__ = [
    "MAX_RECIPIENT_LIST_ROWS",
    "RECIPIENT_LIST_AUDIENCE_TYPE",
    "RecipientListInvalid",
    "RecipientListNotFound",
    "create_recipient_list",
    "get_recipient_list",
    "get_recipient_list_page",
    "is_recipient_list_audience",
]
