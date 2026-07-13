from dataclasses import dataclass, field


@dataclass
class ReplyIoEndpointConfig:
    name: str
    path: str
    # Scope the endpoint requires, per the Reply API docs (a broader scope that includes it also works).
    scope: str
    # Most list endpoints paginate with `top`/`skip` and wrap rows in {"items": [...], "hasMore": bool};
    # a few small catalogs return a bare, unpaginated JSON array.
    paginated: bool = True
    # Reply object IDs are unique per resource within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Reply API v3 list endpoints (https://docs.reply.io/api-reference). All are full refresh only:
# no list endpoint exposes a server-side created/updated timestamp filter, so there is no
# incremental cursor to advance.
REPLY_IO_ENDPOINTS: dict[str, ReplyIoEndpointConfig] = {
    "contacts": ReplyIoEndpointConfig(name="contacts", path="/contacts", scope="contacts:read"),
    "contact_lists": ReplyIoEndpointConfig(name="contact_lists", path="/contact-lists", scope="contacts:read"),
    "accounts": ReplyIoEndpointConfig(name="accounts", path="/contact-accounts", scope="contacts:read"),
    "account_lists": ReplyIoEndpointConfig(name="account_lists", path="/contact-account-lists", scope="contacts:read"),
    "custom_fields": ReplyIoEndpointConfig(
        name="custom_fields", path="/custom-fields", scope="contacts:read", paginated=False
    ),
    "sequences": ReplyIoEndpointConfig(name="sequences", path="/sequences", scope="sequences:read"),
    "tasks": ReplyIoEndpointConfig(name="tasks", path="/tasks", scope="tasks:read"),
    "email_templates": ReplyIoEndpointConfig(name="email_templates", path="/email-templates", scope="sequences:read"),
    "email_template_folders": ReplyIoEndpointConfig(
        name="email_template_folders", path="/email-template-folders", scope="sequences:read", paginated=False
    ),
    "email_accounts": ReplyIoEndpointConfig(name="email_accounts", path="/email-accounts", scope="channels:read"),
    "inbox_threads": ReplyIoEndpointConfig(name="inbox_threads", path="/inbox/threads", scope="inbox:read"),
}

ENDPOINTS = tuple(REPLY_IO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
