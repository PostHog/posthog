"""Enums that cross the stacks facade. No Django imports."""

from posthog.enums import LabeledStrEnum


class DiffStatus(LabeledStrEnum):
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    PUSHED = "pushed"
    STALE = "stale"


class PushStatus(LabeledStrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # The worker stopped without reporting an outcome, so what PostHog holds is unknown until the next diff.
    UNCERTAIN = "uncertain"


class BindingStatus(LabeledStrEnum):
    # Recorded by adopt. The next push binds the entity and creates nothing.
    PENDING = "pending"
    BOUND = "bound"
    # Released to the UI. The next push forgets the entity and deletes nothing.
    DETACHED = "detached"


class BindingOrigin(LabeledStrEnum):
    # The stack's push made the entity, so removing its definition removes the entity.
    CREATED = "created"
    # The entity existed before the stack, so removing its definition releases it and deletes nothing.
    ADOPTED = "adopted"


class ChangeAction(LabeledStrEnum):
    CREATE = "create"
    UPDATE = "update"
    RECREATE = "recreate"
    REMOVE = "remove"
    ADOPT = "adopt"
    RENAME = "rename"
    RELEASE = "release"


class StackErrorKind(LabeledStrEnum):
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INVALID = "invalid"
    FORBIDDEN = "forbidden"
    UNAVAILABLE = "unavailable"


class StackErrorCode(LabeledStrEnum):
    """Every code a stacks error response can carry."""

    STACK_NOT_FOUND = "stack_not_found"
    DIFF_NOT_FOUND = "diff_not_found"
    BINDING_NOT_FOUND = "binding_not_found"
    SECRET_NOT_FOUND = "secret_not_found"
    ENTITY_NOT_FOUND = "entity_not_found"
    STACK_MOVED = "stack_moved"
    STACK_LOCKED = "stack_locked"
    DIFF_NOT_READY = "diff_not_ready"
    DIFF_PUSHED = "diff_pushed"
    DIFF_EXPIRED = "diff_expired"
    PUSH_UNCERTAIN = "push_uncertain"
    CLAIMED_BY_OTHER_STACK = "claimed_by_other_stack"
    ENTITY_ALREADY_BOUND = "entity_already_bound"
    KEY_ALREADY_BOUND = "key_already_bound"
    TOO_MANY_REMOVALS = "too_many_removals"
    INVALID_STACK_NAME = "invalid_stack_name"
    INVALID_SECRET_NAME = "invalid_secret_name"
    SECRET_TOO_LARGE = "secret_too_large"
    INVALID_KEY = "invalid_key"
    DUPLICATE_DEFINITION = "duplicate_definition"
    TOO_MANY_DEFINITIONS = "too_many_definitions"
    DEFINITION_TOO_LARGE = "definition_too_large"
    DEFINITION_TOO_DEEP = "definition_too_deep"
    SECRET_LITERAL = "secret_literal"
    INVALID_DEFINITION = "invalid_definition"
    KIND_UNSUPPORTED = "kind_unsupported"
    IMPERSONATED_PUSH = "impersonated_push"
    USER_REQUIRED = "user_required"
    CALLER_UNAVAILABLE = "caller_unavailable"
    PERMISSION_DENIED = "permission_denied"
    STACKS_UNAVAILABLE = "stacks_unavailable"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    INVALID_INPUT = "invalid_input"
    CONTEXT_PAGES_NOT_ENABLED = "context_pages_not_enabled"
    ORGANIZATION_ADMIN_REQUIRED = "organization_admin_required"
    KIND_NOT_LISTABLE = "kind_not_listable"
    MANAGED_IN_CODE = "managed_in_code"
    REPOSITORY_NOT_CONNECTED = "repository_not_connected"
    TASKS_UNAVAILABLE = "tasks_unavailable"
    NOTHING_TO_RECONCILE = "nothing_to_reconcile"
    CREDENTIAL_NOT_SUPPORTED = "credential_not_supported"
    SECRET_MISSING = "secret_missing"
