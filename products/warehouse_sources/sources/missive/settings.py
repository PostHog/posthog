from dataclasses import field
from enum import StrEnum

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen


class Pagination(StrEnum):
    # `limit` and `offset` query params; a short page is the last one.
    OFFSET = "offset"
    # Newest first, paged backwards with `until` set to the oldest timestamp of the previous page.
    UNTIL = "until"


class Parent(StrEnum):
    CONVERSATIONS = "conversations"
    CONTACT_BOOKS = "contact_books"


@frozen
class MissiveEndpointConfig:
    name: str
    # Path under the API base URL. A fan-out child has an `{id}` placeholder for its parent id.
    path: str
    # Key in the response body that holds the list of rows.
    data_key: str
    pagination: Pagination
    page_size: int
    # For `until` pagination: the row timestamp the API orders by and that `until` filters on.
    cursor_field: str | None = None
    # Query params sent on every page, one full pass per entry.
    param_variants: tuple[dict[str, str], ...] = ({},)
    # For a fan-out child: the endpoint whose rows it iterates, and the column that carries the parent id.
    parent: Parent | None = None
    parent_id_column: str | None = None
    # Copy the variant params onto each row, so the row records which pass read it.
    variant_columns: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Rows change after creation, or an incremental walk reads boundary rows again, so append would duplicate them.
    merge_only: bool = False
    # The task docs page on one second earlier, instead of ending at a full page with one timestamp.
    same_timestamp_page_continues: bool = False
    primary_keys: tuple[str, ...] = ("id",)
    # A creation timestamp that never changes after the row is created.
    partition_key: str | None = None


def _unix_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.Integer,
    }


# `GET /conversations` must name a mailbox. The `All` mailbox holds every conversation the token owner
# can see, closed ones included, except trash and spam.
CONVERSATION_LIST_PARAMS: dict[str, str] = {"all": "true"}

# Conversation entries (messages, comments, posts) have their own UUID and move with their conversation
# when Missive merges two conversations, so `id` alone is the key and a merge updates the row.
MISSIVE_ENDPOINTS: dict[str, MissiveEndpointConfig] = {
    config.name: config
    for config in (
        MissiveEndpointConfig(
            name="conversations",
            path="/conversations",
            data_key="conversations",
            pagination=Pagination.UNTIL,
            page_size=50,
            cursor_field="last_activity_at",
            param_variants=(CONVERSATION_LIST_PARAMS,),
            incremental_fields=[_unix_field("last_activity_at")],
            merge_only=True,
            partition_key="created_at",
        ),
        MissiveEndpointConfig(
            name="messages",
            path="/conversations/{id}/messages",
            data_key="messages",
            pagination=Pagination.UNTIL,
            page_size=10,
            cursor_field="delivered_at",
            parent=Parent.CONVERSATIONS,
            parent_id_column="conversation_id",
            incremental_fields=[_unix_field("delivered_at")],
            merge_only=True,
            partition_key="created_at",
        ),
        MissiveEndpointConfig(
            name="comments",
            path="/conversations/{id}/comments",
            data_key="comments",
            pagination=Pagination.UNTIL,
            page_size=10,
            cursor_field="created_at",
            parent=Parent.CONVERSATIONS,
            parent_id_column="conversation_id",
            incremental_fields=[_unix_field("created_at")],
            merge_only=True,
            partition_key="created_at",
        ),
        MissiveEndpointConfig(
            name="posts",
            path="/conversations/{id}/posts",
            data_key="posts",
            pagination=Pagination.UNTIL,
            page_size=10,
            cursor_field="created_at",
            parent=Parent.CONVERSATIONS,
            parent_id_column="conversation_id",
            incremental_fields=[_unix_field("created_at")],
            merge_only=True,
            partition_key="created_at",
        ),
        MissiveEndpointConfig(
            name="tasks",
            path="/tasks",
            data_key="tasks",
            pagination=Pagination.UNTIL,
            page_size=50,
            cursor_field="last_activity_at",
            incremental_fields=[_unix_field("last_activity_at")],
            merge_only=True,
            same_timestamp_page_continues=True,
        ),
        MissiveEndpointConfig(
            name="contact_books",
            path="/contact_books",
            data_key="contact_books",
            pagination=Pagination.OFFSET,
            page_size=200,
        ),
        MissiveEndpointConfig(
            name="contacts",
            path="/contacts",
            data_key="contacts",
            pagination=Pagination.OFFSET,
            page_size=200,
            parent=Parent.CONTACT_BOOKS,
            parent_id_column="contact_book",
            incremental_fields=[_unix_field("modified_at")],
            merge_only=True,
        ),
        MissiveEndpointConfig(
            name="contact_groups",
            path="/contact_groups",
            data_key="contact_groups",
            pagination=Pagination.OFFSET,
            page_size=200,
            # `kind` is required, so each contact book is read once per kind.
            param_variants=({"kind": "group"}, {"kind": "organization"}),
            variant_columns=True,
            parent=Parent.CONTACT_BOOKS,
            parent_id_column="contact_book",
        ),
        MissiveEndpointConfig(
            name="organizations",
            path="/organizations",
            data_key="organizations",
            pagination=Pagination.OFFSET,
            page_size=200,
        ),
        MissiveEndpointConfig(
            name="users",
            path="/users",
            data_key="users",
            pagination=Pagination.OFFSET,
            page_size=200,
        ),
        MissiveEndpointConfig(
            name="teams",
            path="/teams",
            data_key="teams",
            pagination=Pagination.OFFSET,
            page_size=200,
        ),
        MissiveEndpointConfig(
            name="shared_labels",
            path="/shared_labels",
            data_key="shared_labels",
            pagination=Pagination.OFFSET,
            page_size=200,
        ),
        MissiveEndpointConfig(
            name="responses",
            path="/responses",
            data_key="responses",
            pagination=Pagination.OFFSET,
            page_size=200,
        ),
    )
}

ENDPOINTS = tuple(MISSIVE_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MISSIVE_ENDPOINTS.items() if config.incremental_fields
}

MERGE_ONLY_ENDPOINTS = tuple(name for name, config in MISSIVE_ENDPOINTS.items() if config.merge_only)
