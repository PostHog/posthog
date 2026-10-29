"""Supabase auth emails: Supabase's Send Email Hook sends each auth email through a transactional email template."""

from products.messaging.backend.facade.contracts import (
    SupabaseAuthEmailSettings,
    SupabaseAuthEmailSettingsInvalid,
    SupabaseEmailActionType,
    SupabaseHookResult,
)
from products.messaging.backend.services.supabase_auth_email_templates import STARTER_EMAIL_TYPES
from products.messaging.backend.services.supabase_auth_emails import (
    MAX_HOOK_BODY_BYTES,
    create_starter_templates,
    delete_settings,
    get_settings,
    handle_send_email_hook,
    save_settings,
    template_workflow_ids,
)

__all__ = [
    "MAX_HOOK_BODY_BYTES",
    "STARTER_EMAIL_TYPES",
    "SupabaseAuthEmailSettings",
    "SupabaseAuthEmailSettingsInvalid",
    "SupabaseEmailActionType",
    "SupabaseHookResult",
    "create_starter_templates",
    "delete_settings",
    "get_settings",
    "handle_send_email_hook",
    "save_settings",
    "template_workflow_ids",
]
