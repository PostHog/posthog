/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `queued` - Queued
 * * `failed` - Failed
 * * `sent` - Sent
 * * `delivered` - Delivered
 * * `bounced` - Bounced
 * * `complained` - Complained
 */
export type EmailDeliveryStatusEnumApi = (typeof EmailDeliveryStatusEnumApi)[keyof typeof EmailDeliveryStatusEnumApi]

export const EmailDeliveryStatusEnumApi = {
    Queued: 'queued',
    Failed: 'failed',
    Sent: 'sent',
    Delivered: 'delivered',
    Bounced: 'bounced',
    Complained: 'complained',
} as const

export interface EmailStatusApi {
    /** The `message_id` that the send returned. */
    id: string
    /** What happened to the email. `queued` means it waits to go out. `sent` means PostHog handed it to the email provider. `failed` means it was not sent, and `reason` says why. A rerun of the send can still move it to `sent`. `delivered` means the recipient's mail server accepted it. `bounced` and `complained` come later from the recipient's mail provider.
     *
     * * `queued` - Queued
     * * `failed` - Failed
     * * `sent` - Sent
     * * `delivered` - Delivered
     * * `bounced` - Bounced
     * * `complained` - Complained */
    status: EmailDeliveryStatusEnumApi
    /** When the send was queued. */
    created_at: string
    /** When the email reached its current status. */
    status_at: string
    /**
     * Why a failed email was not sent, or the bounce type of a bounced email. A failed send has `provider_error`, or `provider_rejected` when the provider refused the email after it accepted the send. A skipped send has `recipient_suppressed`, `recipient_unreachable`, `recipient_opted_out`, `missing_recipient`, `sending_paused`, `sending_suspended` or `frequency_capped`. A run that stopped before the send has `canceled`, `workflow_unavailable` or an error kind such as `timeout`, and more error kinds can be added. A bounce has `hard`, `soft` or `unknown`. Null otherwise.
     * @nullable
     */
    reason: string | null
}

/**
 * Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`.
 */
export type SendEmailApiMessageData = { [key: string]: unknown }

export interface TransactionalEmailIdentifiersApi {
    /**
     * Distinct ID of the recipient's person. The email's engagement events (sent, delivered, opened, clicked, bounced) and the send itself are recorded against that person. Defaults to the recipient's email address. The template can't read the person's properties, so pass everything it needs in `message_data`.
     * @maxLength 400
     * @nullable
     */
    distinct_id?: string | null
}

export interface SendEmailTemplateApi {
    /** ID of the email template to send. The template must be made transactional first. Give either `id` or `key`. */
    id?: string
    /**
     * Key of the email template to send, as uploaded with `PUT /api/projects/@current/messaging_templates/by_key/{key}/`. Give either `id` or `key`.
     * @maxLength 400
     * @pattern ^[a-zA-Z0-9_-]+$
     */
    key?: string
    /**
     * Content hash of the template you hold, as an upload's `content_hash`. When PostHog doesn't hold that content as the current content or one of the last 100 contents it replaced, the send answers `409 template_outdated` and sends nothing. Only with `key`.
     * @pattern ^v1:[0-9a-f]{64}$
     */
    hash?: string
}

export interface SendEmailApi {
    /** Email address of the recipient. */
    to: string
    /** Who the email is for, used to attribute engagement events. */
    identifiers?: TransactionalEmailIdentifiersApi
    /** Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`. */
    message_data?: SendEmailApiMessageData
    /** The transactional email template to send. Send either `template` or `template_key`. */
    template?: SendEmailTemplateApi
    /**
     * Names an email whose content your code rendered, such as `order-shipped`, so its metrics, logs and status group under it. Letters, numbers, hyphens (-) and underscores (_) only. Send it with `subject` and `html` or `text`. PostHog sends the content as is and never stores it as a template. Once you upload a template under this key, these sends run through that template's workflow, so their metrics and logs group with the template from then on.
     * @maxLength 400
     * @pattern ^[a-zA-Z0-9_-]+$
     */
    template_key?: string
    /**
     * Distinct ID of the recipient's person. The send and its engagement events are recorded against that person. Defaults to `identifiers.distinct_id`, then to the recipient's email address.
     * @maxLength 400
     */
    distinct_id?: string
    /** Subject of the email your code rendered. */
    subject?: string
    /** HTML body of the email your code rendered. */
    html?: string
    /** Plain text body of the email your code rendered. Without it, PostHog derives the text from `html`. */
    text?: string
    /**
     * Addresses replies to the email go to. A send by `template.id` doesn't take it.
     * @maxItems 10
     */
    reply_to?: string[]
    /** Whether the engagement events (sent, delivered, opened, clicked, bounced) of the email are captured as analytics events of the recipient. Defaults to true. A project whose admin turned engagement capture off captures nothing, whatever the send says. A send by `template.id` takes it only in the beta for sending email from code. */
    capture_engagement?: boolean
    /** Sender of the email, as `security@example.com` or `Example <security@example.com>`, on a verified domain of the project. Without it, a send with `template_key` goes out from the project's default sender, and a send by `template.key` from its template's sender. A send by `template.id` doesn't take it. */
    from?: string
}

export interface SendEmailWarningApi {
    /** Stable code of the warning, such as `template_superseded`. */
    code: string
    /** What happened. */
    detail: string
    /** What you can change, if the warning isn't what you want. */
    fix: string
}

export interface SendEmailResponseApi {
    /** ID of the queued send. Delivery and engagement are reported against the template asynchronously. */
    message_id: string
    /** True when an earlier request with the same `Idempotency-Key` already queued this email. No new email was sent, and `message_id` is the earlier send's ID. */
    replayed: boolean
    /** Things to know about the queued email. Left out when there are none. */
    warnings?: SendEmailWarningApi[]
}

/**
 * * `marketing` - Marketing
 * * `transactional` - Transactional
 */
export type MessageCategoryTypeEnumApi = (typeof MessageCategoryTypeEnumApi)[keyof typeof MessageCategoryTypeEnumApi]

export const MessageCategoryTypeEnumApi = {
    Marketing: 'marketing',
    Transactional: 'transactional',
} as const

export interface MessageCategoryApi {
    /** Category ID. Workflow message steps take it as `message_category_id`, and the opt-out of messages step takes it as its `category_id` input. */
    readonly id: string
    /**
     * Stable identifier for the category, unique within the project, for example `newsletter`. Opt-out lists and preference imports refer to categories by key. You can't change the key after creation.
     * @maxLength 64
     */
    key: string
    /**
     * Display name of the category, shown in the PostHog app.
     * @maxLength 128
     */
    name: string
    /** Internal notes about which messages belong to this category. Recipients don't see it. */
    description?: string
    /** Description that recipients see next to the category on the preferences page. */
    public_description?: string
    /** `marketing` (the default): recipients can opt out of it, and sends skip recipients who did. `transactional`: for messages a recipient must get, such as receipts or password resets. Sends ignore opt-outs, and the category doesn't appear on the preferences page. Set `message_category_type` on a workflow message step to the type of its category.
     *
     * * `marketing` - Marketing
     * * `transactional` - Transactional */
    category_type?: MessageCategoryTypeEnumApi
    /** When the category was created. */
    readonly created_at: string
    /** When the category was last changed. */
    readonly updated_at: string
    /**
     * ID of the user who created the category. Null when the user no longer exists.
     * @nullable
     */
    readonly created_by: number | null
    /** Set to true to archive the category. Archived categories don't appear in lists. */
    deleted?: boolean
}

export interface PaginatedMessageCategoryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MessageCategoryApi[]
}

export interface PatchedMessageCategoryApi {
    /** Category ID. Workflow message steps take it as `message_category_id`, and the opt-out of messages step takes it as its `category_id` input. */
    readonly id?: string
    /**
     * Stable identifier for the category, unique within the project, for example `newsletter`. Opt-out lists and preference imports refer to categories by key. You can't change the key after creation.
     * @maxLength 64
     */
    key?: string
    /**
     * Display name of the category, shown in the PostHog app.
     * @maxLength 128
     */
    name?: string
    /** Internal notes about which messages belong to this category. Recipients don't see it. */
    description?: string
    /** Description that recipients see next to the category on the preferences page. */
    public_description?: string
    /** `marketing` (the default): recipients can opt out of it, and sends skip recipients who did. `transactional`: for messages a recipient must get, such as receipts or password resets. Sends ignore opt-outs, and the category doesn't appear on the preferences page. Set `message_category_type` on a workflow message step to the type of its category.
     *
     * * `marketing` - Marketing
     * * `transactional` - Transactional */
    category_type?: MessageCategoryTypeEnumApi
    /** When the category was created. */
    readonly created_at?: string
    /** When the category was last changed. */
    readonly updated_at?: string
    /**
     * ID of the user who created the category. Null when the user no longer exists.
     * @nullable
     */
    readonly created_by?: number | null
    /** Set to true to archive the category. Archived categories don't appear in lists. */
    deleted?: boolean
}

export interface AddOptOutRequestApi {
    /**
     * The recipient identifier to opt out (e.g. email address).
     * @maxLength 512
     */
    identifier: string
    /** Optional message category key. If omitted, the recipient is opted out of all marketing messages. */
    category_key?: string
}

export interface MessagePreferencesApi {
    /** Server-assigned UUID for this recipient's preference record. */
    readonly id: string
    /** The recipient identifier (e.g. email address). */
    identifier: string
    /** When the preference was last updated. */
    updated_at: string
    /** Map of category ID to preference status (`OPTED_IN`, `OPTED_OUT` or `NO_PREFERENCE`). The reserved `$all` key covers every marketing message. */
    preferences: unknown
}

export interface BulkOptOutEntryApi {
    /**
     * The recipient identifier to opt out (e.g. email address).
     * @maxLength 512
     */
    identifier: string
    /** Message category key for this recipient. Overrides the request-level category_key. */
    category_key?: string
}

export interface BulkAddOptOutsRequestApi {
    /** Recipients to opt out, at most 1000 per request. */
    opt_outs: BulkOptOutEntryApi[]
    /** Message category key applied to entries without their own. If omitted, recipients are opted out of all marketing messages. */
    category_key?: string
}

export interface BulkAddOptOutsResultApi {
    /** Number of opt-out entries received. */
    total: number
    /** Number of recipient and category pairs recorded as opted out. */
    opted_out: number
    /** Number of entries skipped because their category_key doesn't exist. */
    skipped: number
    /** The first few entry-level problems, so the caller can fix their list. */
    errors: string[]
}

export interface MessagingErrorApi {
    /** Human-readable description of what went wrong. */
    error: string
}

export interface GenerateLinkRequestApi {
    /**
     * Recipient to generate the link for. Defaults to the requesting user's own email address.
     * @maxLength 512
     */
    recipient?: string
}

export interface PreferencesLinkApi {
    /** Token-gated URL where the recipient can manage their preferences. */
    preferences_url: string
}

/**
 * OpenAPI shape for the paginated opt-outs response, so the generated clients get the
 * {count, next, previous, results} envelope instead of an untyped object.
 */
export interface PaginatedOptOutsApi {
    /** Total number of opted-out recipients for the category. */
    count: number
    /**
     * URL for the next page, or null on the last page.
     * @nullable
     */
    next: string | null
    /**
     * URL for the previous page, or null on the first page.
     * @nullable
     */
    previous: string | null
    results: MessagePreferencesApi[]
}

export interface RemoveOptOutRequestApi {
    /**
     * The recipient identifier to opt back in (e.g. email address).
     * @maxLength 512
     */
    identifier: string
    /** Optional message category key. If omitted, the recipient is opted back in to all marketing messages. */
    category_key?: string
}

export interface WebhookUrlApi {
    /** URL to register in Customer.io so it posts subscription changes to PostHog. */
    url: string
}

/**
 * * `customerio` - Customer.io
 */
export type ImportProviderKeyEnumApi = (typeof ImportProviderKeyEnumApi)[keyof typeof ImportProviderKeyEnumApi]

export const ImportProviderKeyEnumApi = {
    Customerio: 'customerio',
} as const

/**
 * * `queued` - Waiting to start
 * * `running` - Importing
 * * `completed` - Imported
 * * `failed` - Failed
 */
export type ProviderImportStatusEnumApi = (typeof ProviderImportStatusEnumApi)[keyof typeof ProviderImportStatusEnumApi]

export const ProviderImportStatusEnumApi = {
    Queued: 'queued',
    Running: 'running',
    Completed: 'completed',
    Failed: 'failed',
} as const

/**
 * * `pending` - Not started
 * * `running` - Importing
 * * `completed` - Imported
 * * `failed` - Failed
 */
export type ImportStepStatusEnumApi = (typeof ImportStepStatusEnumApi)[keyof typeof ImportStepStatusEnumApi]

export const ImportStepStatusEnumApi = {
    Pending: 'pending',
    Running: 'running',
    Completed: 'completed',
    Failed: 'failed',
} as const

export interface ImportStepProgressApi {
    /** Step key, for example `suppressions`. */
    key: string
    /** Display name of the step. */
    label: string
    /** `pending` until the step starts, `running` while it imports or waits to retry, then `completed` or `failed`.
     *
     * * `pending` - Not started
     * * `running` - Importing
     * * `completed` - Imported
     * * `failed` - Failed */
    status: ImportStepStatusEnumApi
    /** How many records the step read from the provider so far. */
    processed: number
    /** How many records the step added or updated in PostHog so far. Records that already existed and need no change may not count. */
    imported: number
    /** Problems with single records that did not fail the step. */
    warnings: string[]
    /**
     * The error from the step's most recent failed attempt. A running step retries after an error; a failed step stopped.
     * @nullable
     */
    last_error: string | null
}

export interface ProviderImportRunApi {
    /** Import run ID. */
    id: string
    /** The provider the run imports from.
     *
     * * `customerio` - Customer.io */
    provider: ImportProviderKeyEnumApi
    /** `queued` until the first step starts, `running`, then `completed` when every step completed or `failed` when any step failed.
     *
     * * `queued` - Waiting to start
     * * `running` - Importing
     * * `completed` - Imported
     * * `failed` - Failed */
    status: ProviderImportStatusEnumApi
    /** Progress of each selected step, in run order. */
    steps: ImportStepProgressApi[]
    /** When the run was requested. */
    created_at: string
    /**
     * When the first step started.
     * @nullable
     */
    started_at: string | null
    /**
     * When the last step ended.
     * @nullable
     */
    finished_at: string | null
}

export interface StartProviderImportApi {
    /** The provider to import from.
     *
     * * `customerio` - Customer.io */
    provider: ImportProviderKeyEnumApi
    /**
     * Keys of the steps to run, from the `providers` endpoint. They run in the provider's order, whatever order you send.
     * @minItems 1
     * @items.maxLength 64
     */
    steps: string[]
    /** The provider's API key. For Customer.io, an App API key. Leave it out to reuse the stored key. */
    api_key?: string
}

export interface ImportStepOptionApi {
    /** Step key to send in `steps` when starting an import, for example `suppressions`. */
    key: string
    /** Display name of the step. */
    label: string
    /** What the step imports and where it lands in PostHog. */
    description: string
}

export interface ImportProviderOptionApi {
    /** Provider key to send when starting an import.
     *
     * * `customerio` - Customer.io */
    key: ImportProviderKeyEnumApi
    /** Display name of the provider. */
    label: string
    /** What the provider can import, in the order the steps run. */
    steps: ImportStepOptionApi[]
}

/**
 * Supabase email action type (such as `signup` or `recovery`) to the transactional message template that sends it. An auth email with no template fails in Supabase.
 */
export type SupabaseAuthEmailSettingsApiTemplates = { [key: string]: string }

/**
 * * `signup` - Confirm sign up
 * * `invite` - Invite user
 * * `magiclink` - Magic link
 * * `email` - Email sign-in code
 * * `recovery` - Reset password
 * * `email_change` - Change email address
 * * `reauthentication` - Reauthentication
 * * `password_changed_notification` - Password changed
 * * `email_changed_notification` - Email address changed
 * * `phone_changed_notification` - Phone number changed
 * * `identity_linked_notification` - Sign-in method linked
 * * `identity_unlinked_notification` - Sign-in method removed
 * * `mfa_factor_enrolled_notification` - MFA method added
 * * `mfa_factor_unenrolled_notification` - MFA method removed
 */
export type SupabaseEmailActionTypeEnumApi =
    (typeof SupabaseEmailActionTypeEnumApi)[keyof typeof SupabaseEmailActionTypeEnumApi]

export const SupabaseEmailActionTypeEnumApi = {
    Signup: 'signup',
    Invite: 'invite',
    Magiclink: 'magiclink',
    Email: 'email',
    Recovery: 'recovery',
    EmailChange: 'email_change',
    Reauthentication: 'reauthentication',
    PasswordChangedNotification: 'password_changed_notification',
    EmailChangedNotification: 'email_changed_notification',
    PhoneChangedNotification: 'phone_changed_notification',
    IdentityLinkedNotification: 'identity_linked_notification',
    IdentityUnlinkedNotification: 'identity_unlinked_notification',
    MfaFactorEnrolledNotification: 'mfa_factor_enrolled_notification',
    MfaFactorUnenrolledNotification: 'mfa_factor_unenrolled_notification',
} as const

export interface SupabaseEmailTypeApi {
    /** The `email_action_type` Supabase sends for this email.
     *
     * * `signup` - Confirm sign up
     * * `invite` - Invite user
     * * `magiclink` - Magic link
     * * `email` - Email sign-in code
     * * `recovery` - Reset password
     * * `email_change` - Change email address
     * * `reauthentication` - Reauthentication
     * * `password_changed_notification` - Password changed
     * * `email_changed_notification` - Email address changed
     * * `phone_changed_notification` - Phone number changed
     * * `identity_linked_notification` - Sign-in method linked
     * * `identity_unlinked_notification` - Sign-in method removed
     * * `mfa_factor_enrolled_notification` - MFA method added
     * * `mfa_factor_unenrolled_notification` - MFA method removed */
    value: SupabaseEmailActionTypeEnumApi
    /** What the email is for, in words a person reads. */
    label: string
    /** Whether creating starter templates makes a template for this email. */
    has_starter_template: boolean
}

export interface SupabaseAuthEmailSettingsApi {
    /** The Supabase project URL, such as https://abcdefgh.supabase.co. Confirmation links point at its /auth/v1/verify endpoint. */
    supabase_url: string
    /** Whether a Send Email Hook secret is stored. The secret itself is never returned. */
    has_hook_secret: boolean
    /** Supabase email action type (such as `signup` or `recovery`) to the transactional message template that sends it. An auth email with no template fails in Supabase. */
    templates: SupabaseAuthEmailSettingsApiTemplates
    /** The URL to paste into Supabase as the HTTPS endpoint of the Send Email Hook. */
    hook_url: string
    /** Every email Supabase can send through the hook, core auth emails first. */
    email_types: SupabaseEmailTypeApi[]
}

/**
 * Supabase email action type to the id of the email template that sends it. Each template must be transactional and marked sensitive. This replaces the whole mapping: include every type to keep, and leave a type out to unmap it. A core auth email with no template fails in Supabase, and a notification with no template is skipped. Valid action types: signup, invite, magiclink, email, recovery, email_change, reauthentication, password_changed_notification, email_changed_notification, phone_changed_notification, identity_linked_notification, identity_unlinked_notification, mfa_factor_enrolled_notification, mfa_factor_unenrolled_notification.
 */
export type PatchedSupabaseAuthEmailSettingsUpdateApiTemplates = { [key: string]: string }

export interface PatchedSupabaseAuthEmailSettingsUpdateApi {
    /**
     * The Supabase project URL, such as https://abcdefgh.supabase.co, from the project's API settings in the Supabase dashboard. It must use https.
     * @maxLength 200
     */
    supabase_url?: string
    /**
     * The Send Email Hook secret, starting with v1,whsec_. Supabase generates it under Authentication, Hooks, Send Email hook. Leave it out to keep the stored secret.
     * @maxLength 500
     */
    hook_secret?: string
    /** Supabase email action type to the id of the email template that sends it. Each template must be transactional and marked sensitive. This replaces the whole mapping: include every type to keep, and leave a type out to unmap it. A core auth email with no template fails in Supabase, and a notification with no template is skipped. Valid action types: signup, invite, magiclink, email, recovery, email_change, reauthentication, password_changed_notification, email_changed_notification, phone_changed_notification, identity_linked_notification, identity_unlinked_notification, mfa_factor_enrolled_notification, mfa_factor_unenrolled_notification. */
    templates?: PatchedSupabaseAuthEmailSettingsUpdateApiTemplates
}

export interface AddSuppressionRequestApi {
    /**
     * The email address to suppress. Will not receive any messages until removed.
     * @maxLength 512
     */
    identifier: string
}

/**
 * * `BOUNCE` - Bounce
 * * `MANUAL` - Manual
 * * `COMPLAINT` - Complaint
 */
export type SuppressionSourceEnumApi = (typeof SuppressionSourceEnumApi)[keyof typeof SuppressionSourceEnumApi]

export const SuppressionSourceEnumApi = {
    Bounce: 'BOUNCE',
    Manual: 'MANUAL',
    Complaint: 'COMPLAINT',
} as const

export interface MessageSuppressionApi {
    /** Server-assigned UUID for this suppression entry. */
    readonly id: string
    /** Normalized recipient email address. Suppression is keyed on this value, per team. */
    readonly identifier: string
    /** How the entry landed on the list: `BOUNCE` for automatic (bounce-driven), `COMPLAINT` for automatic (the recipient reported a message as spam), `MANUAL` for user-added via the UI/API.
     *
     * * `BOUNCE` - Bounce
     * * `MANUAL` - Manual
     * * `COMPLAINT` - Complaint */
    readonly source: SuppressionSourceEnumApi
    /**
     * Human-readable reason for the suppression (e.g. 'Auto-suppressed after 5 consecutive soft bounces').
     * @nullable
     */
    readonly reason: string | null
    /** Rolling count of consecutive soft bounces with no successful delivery in between. Reset to 0 on any successful delivery. Ignored for MANUAL entries. */
    readonly transient_bounce_count: number
    /**
     * Timestamp of the most recent bounce, if any.
     * @nullable
     */
    readonly last_bounce_at: string | null
    /**
     * SMTP diagnostic string from the most recent bounce (e.g. '550 5.1.1 user unknown'), kept for visibility.
     * @nullable
     */
    readonly last_bounce_diagnostic: string | null
    /** Whether the address is actively suppressed. A BOUNCE row can exist while still only counting bounces (suppressed=false) before it crosses the threshold. */
    readonly suppressed: boolean
    /**
     * Timestamp when the address was first suppressed.
     * @nullable
     */
    readonly suppressed_at: string | null
    /** When the row was first created (first bounce or manual add). */
    readonly created_at: string
    /** When the row was last touched by any write. */
    readonly updated_at: string
}

/**
 * OpenAPI shape for the paginated suppressions response. Declared so drf-spectacular emits
 * the {count, next, previous, results} envelope on the generated client, rather than a bare
 * array — which the frontend actually receives at runtime.
 */
export interface PaginatedMessageSuppressionApi {
    /** Total number of suppressed recipients for the team. */
    count: number
    /**
     * URL for the next page, or null on the last page.
     * @nullable
     */
    next: string | null
    /**
     * URL for the previous page, or null on the first page.
     * @nullable
     */
    previous: string | null
    results: MessageSuppressionApi[]
}

/**
 * * `liquid` - liquid
 */
export type MessageTemplateContentTemplatingEnumApi =
    (typeof MessageTemplateContentTemplatingEnumApi)[keyof typeof MessageTemplateContentTemplatingEnumApi]

export const MessageTemplateContentTemplatingEnumApi = {
    Liquid: 'liquid',
} as const

export interface EmailTemplateSenderApi {
    /**
     * Address to send from instead of the sender's own. Must be on the sender's verified domain. Supports Liquid templating. Leave out or empty to use the sender's address.
     * @maxLength 254
     */
    email?: string
    /** Sender name shown in the inbox instead of the sender's own. Supports Liquid templating. Leave out or empty to use the sender's name. */
    name?: string
    /** ID of the project's email sender integration that sends this email. Transactional sends need a verified sender. */
    integrationId: number
}

/**
 * Highest htmlID suffix per element type, e.g. {"u_row": 1, "u_content_text": 2}.
 */
export type EmailTemplateApiDesignCounters = { [key: string]: unknown }

export type EmailTemplateApiDesignBodyRowsItem = { [key: string]: unknown }

export type EmailTemplateApiDesignBodyHeadersItem = { [key: string]: unknown }

export type EmailTemplateApiDesignBodyFootersItem = { [key: string]: unknown }

/**
 * Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor.
 */
export type EmailTemplateApiDesignBodyValues = { [key: string]: unknown }

export type EmailTemplateApiDesignBody = {
    /** Any unique string. */
    id?: string
    /** Rows of {id, cells, columns[{id, contents[{id, type, values}], values}], values}. */
    rows: EmailTemplateApiDesignBodyRowsItem[]
    headers?: EmailTemplateApiDesignBodyHeadersItem[]
    footers?: EmailTemplateApiDesignBodyFootersItem[]
    /** Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor. */
    values?: EmailTemplateApiDesignBodyValues
    [key: string]: unknown
}

/**
 * Design JSON for PostHog's visual email editor — the authoring surface and source of truth. The server renders the sent email from it, and it opens as editable blocks in the editor. Full schema in the designing-email-templates skill.
 */
export type EmailTemplateApiDesign = {
    /** Highest htmlID suffix per element type, e.g. {"u_row": 1, "u_content_text": 2}. */
    counters?: EmailTemplateApiDesignCounters
    /** Design schema version, e.g. 16. */
    schemaVersion: number
    body: EmailTemplateApiDesignBody
    [key: string]: unknown
}

export interface EmailTemplateApi {
    /** Email subject line. Supports Liquid templating. Required in `content` for email-type templates. A `draft_content` may leave it blank until it is published. */
    subject?: string
    /** Plain-text fallback body for clients that can't render the email. */
    text?: string
    /** Preview text that most inboxes show after the subject. Supports Liquid templating. */
    preheader?: string
    /** Rendered email body — derived from the design at save time. The visual editor's save path supplies it directly; omit it otherwise. */
    html?: string
    /** Design JSON for PostHog's visual email editor — the authoring surface and source of truth. The server renders the sent email from it, and it opens as editable blocks in the editor. Full schema in the designing-email-templates skill. */
    design?: EmailTemplateApiDesign
    /** The sender a transactional template sends from. A template made transactional without one gets the sender it was made transactional with. */
    from?: EmailTemplateSenderApi
    /** Reply-to address for a transactional template. Separate several addresses with commas. Supports Liquid templating. Leave empty to use the sender's default reply-to. */
    replyTo?: string
}

export interface MessageTemplateContentApi {
    /** Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.
     *
     * * `liquid` - liquid */
    templating?: MessageTemplateContentTemplatingEnumApi
    /** Email message content. Replaced as a whole on update — send the complete object. */
    email?: EmailTemplateApi | null
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Student: 'student',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * * `gui` - GUI
 * * `code` - Code
 */
export type TemplateManagedByEnumApi = (typeof TemplateManagedByEnumApi)[keyof typeof TemplateManagedByEnumApi]

export const TemplateManagedByEnumApi = {
    Gui: 'gui',
    Code: 'code',
} as const

export interface MessageTemplateApi {
    readonly id: string
    /**
     * Human-readable template name shown in the library.
     * @maxLength 400
     */
    name: string
    /** What the template is for and when to use it. */
    description?: string
    /**
     * Tags for organizing templates, for example by team or use case. Tags are shared with the rest of the project. Omit to keep the current tags, send an empty list to remove them all.
     * @maxItems 10
     * @items.maxLength 255
     */
    tags?: string[]
    readonly created_at: string
    readonly updated_at: string
    /** Template content keyed by channel. Replaced as a whole on update, not merged. */
    content?: MessageTemplateContentApi
    readonly created_by: UserBasicApi
    /**
     * Message channel of the template. Currently 'email'.
     * @maxLength 24
     */
    type?: string
    /**
     * Message category ID to file the template under. Must belong to the same project.
     * @nullable
     */
    message_category?: string | null
    /** Soft-delete flag. Set true to remove the template from the library. */
    deleted?: boolean
    /** For emails that carry login codes, reset links or other secrets. PostHog keeps no copy of each sent email's body or filled-in subject, and clicked links keep only the site address. Can change at any time. */
    sensitive?: boolean
    /**
     * The workflow that sends this template over the transactional email API. Null until the template is made transactional. Each content save writes a new version of it.
     * @nullable
     */
    readonly transactional_hog_flow_id: string | null
    /** Unpublished edits to a transactional template's content. Sends keep using `content`. Saving `content` publishes it and clears the draft. Set null to discard the draft. */
    draft_content?: MessageTemplateContentApi | null
    /**
     * Stable identifier code uses to upload and send this template, unique within the project. Null for templates that have no key. Set once, by the first upload or by a PATCH whose only field is `key`.
     * @nullable
     */
    readonly key: string | null
    /** Who owns the content. `code` when it was uploaded from a repository: PostHog then refuses edits, and the template changes through its next upload. To edit it in PostHog, send a PATCH whose only field is `managed_by` set to `gui`. `gui` or null when it is edited in PostHog.
     *
     * * `gui` - GUI
     * * `code` - Code */
    readonly managed_by: TemplateManagedByEnumApi | null
    /**
     * Repository the template was last uploaded from, such as `github.com/example/app`.
     * @nullable
     */
    readonly source_repository: string | null
    /**
     * Path of the template file in the source repository.
     * @nullable
     */
    readonly source_path: string | null
    /**
     * Commit or branch the template was last uploaded from.
     * @nullable
     */
    readonly source_ref: string | null
    /**
     * Hash of the published subject, preheader, HTML and text, as `v1:` and 64 hex characters. Changes with every save that changes them.
     * @nullable
     */
    readonly content_hash: string | null
}

export interface PaginatedMessageTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MessageTemplateApi[]
}

export interface TemplateErrorApi {
    /** Error class, such as `invalid_request`. */
    type: string
    /** Stable error code to branch on, such as `invalid_template_key`. */
    code: string
    /** What went wrong. */
    detail: string
    /**
     * The request field the error is about, if any.
     * @nullable
     */
    attr: string | null
    /** Why PostHog refuses the request. */
    why?: string
    /** What to change before you retry. */
    fix?: string
    /** Documentation for this error code. */
    docs_url?: string
}

/**
 * * `gui` - GUI
 */
export type TemplateReleasedToEnumApi = (typeof TemplateReleasedToEnumApi)[keyof typeof TemplateReleasedToEnumApi]

export const TemplateReleasedToEnumApi = {
    Gui: 'gui',
} as const

export interface PatchedMessageTemplateUpdateApi {
    readonly id?: string
    /**
     * Human-readable template name shown in the library.
     * @maxLength 400
     */
    name?: string
    /** What the template is for and when to use it. */
    description?: string
    /**
     * Tags for organizing templates, for example by team or use case. Tags are shared with the rest of the project. Omit to keep the current tags, send an empty list to remove them all.
     * @maxItems 10
     * @items.maxLength 255
     */
    tags?: string[]
    readonly created_at?: string
    readonly updated_at?: string
    /** Template content keyed by channel. Replaced as a whole on update, not merged. */
    content?: MessageTemplateContentApi
    readonly created_by?: UserBasicApi
    /**
     * Message channel of the template. Currently 'email'.
     * @maxLength 24
     */
    type?: string
    /**
     * Message category ID to file the template under. Must belong to the same project.
     * @nullable
     */
    message_category?: string | null
    /** Soft-delete flag. Set true to remove the template from the library. */
    deleted?: boolean
    /** For emails that carry login codes, reset links or other secrets. PostHog keeps no copy of each sent email's body or filled-in subject, and clicked links keep only the site address. Can change at any time. */
    sensitive?: boolean
    /**
     * The workflow that sends this template over the transactional email API. Null until the template is made transactional. Each content save writes a new version of it.
     * @nullable
     */
    readonly transactional_hog_flow_id?: string | null
    /** Unpublished edits to a transactional template's content. Sends keep using `content`. Saving `content` publishes it and clears the draft. Set null to discard the draft. */
    draft_content?: MessageTemplateContentApi | null
    /**
     * Give a template that has no key one, so code can take it over: the next upload under this key updates this template and keeps its id, workflow and sender. Code sends that already use this key keep their own workflow until that upload, then run through this template's workflow. Send it as the only field of the PATCH. Letters, digits, hyphens (-) and underscores (_). Set once: a template that has a key keeps it.
     * @maxLength 400
     */
    key?: string
    /** Send `gui` as the only field to stop managing a template in code, so it can be edited in PostHog. It keeps its key, so the next upload under that key manages it in code again.
     *
     * * `gui` - GUI */
    managed_by?: TemplateReleasedToEnumApi
    /**
     * Repository the template was last uploaded from, such as `github.com/example/app`.
     * @nullable
     */
    readonly source_repository?: string | null
    /**
     * Path of the template file in the source repository.
     * @nullable
     */
    readonly source_path?: string | null
    /**
     * Commit or branch the template was last uploaded from.
     * @nullable
     */
    readonly source_ref?: string | null
    /**
     * Hash of the published subject, preheader, HTML and text, as `v1:` and 64 hex characters. Changes with every save that changes them.
     * @nullable
     */
    readonly content_hash?: string | null
}

/**
 * * `update_content` - update_content
 * * `update_column` - update_column
 * * `update_row` - update_row
 * * `update_body` - update_body
 * * `add_content` - add_content
 * * `remove_content` - remove_content
 * * `move_content` - move_content
 * * `add_row` - add_row
 * * `remove_row` - remove_row
 */
export type EmailTemplateDesignOperationEnumApi =
    (typeof EmailTemplateDesignOperationEnumApi)[keyof typeof EmailTemplateDesignOperationEnumApi]

export const EmailTemplateDesignOperationEnumApi = {
    UpdateContent: 'update_content',
    UpdateColumn: 'update_column',
    UpdateRow: 'update_row',
    UpdateBody: 'update_body',
    AddContent: 'add_content',
    RemoveContent: 'remove_content',
    MoveContent: 'move_content',
    AddRow: 'add_row',
    RemoveRow: 'remove_row',
} as const

export interface DesignOperationApi {
    /** Design edit. update_content {id, patch}: deep-merge patch into the content block's fields (a null leaf deletes that key) — the surgical path, e.g. change just values.text. update_row / update_column {id, patch} and update_body {patch}: same deep-merge for row/column/body-level settings. add_content {column_id, content, index?}: insert a content block into a column (id and Unlayer numbering are filled in for you). remove_content {id} / move_content {id, column_id, index?}: delete or relocate a block. add_row {row, index?} / remove_row {id}: add or delete a row.
     *
     * * `update_content` - update_content
     * * `update_column` - update_column
     * * `update_row` - update_row
     * * `update_body` - update_body
     * * `add_content` - add_content
     * * `remove_content` - remove_content
     * * `move_content` - move_content
     * * `add_row` - add_row
     * * `remove_row` - remove_row */
    op: EmailTemplateDesignOperationEnumApi
    /** Target node id. Required for update_content/column/row, remove_content, remove_row, move_content. */
    id?: string
    /** Target column id. Required for add_content and move_content. */
    column_id?: string
    /** update_* only. Partial fields deep-merged into the existing node; a null leaf deletes that key. e.g. {values: {text: '<p>Hi</p>'}} changes only the block's text. */
    patch?: unknown
    /** add_content only. A content block {type, values: {...}}; omit id and values._meta — they're assigned server-side. type is one of text, heading, button, image, divider, html, etc. */
    content?: unknown
    /** add_row only. A full row {cells, columns: [{contents: [...], values}], values}; ids and Unlayer numbering are assigned server-side for the row and everything nested in it. */
    row?: unknown
    /** add_*\/move_content only. 0-based insert position; omit to append to the end. */
    index?: number
}

export interface PatchedDesignPatchApi {
    /** Ordered edits applied atomically to a template's Unlayer design: the stored design is read, the ops are applied in order, the result is validated and re-rendered to HTML, and it's saved only if valid — otherwise the template is unchanged. Reference blocks by id so you never resend the whole design. */
    operations?: DesignOperationApi[]
}

export interface MakeTransactionalApi {
    /**
     * ID of the verified email sender integration the email is sent from. Defaults to the project's default sender.
     * @nullable
     */
    from_integration_id?: number | null
}

/**
 * Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`.
 */
export type SendTransactionalEmailApiMessageData = { [key: string]: unknown }

export interface SendTransactionalEmailApi {
    /** Email address of the recipient. */
    to: string
    /** Who the email is for, used to attribute engagement events. */
    identifiers?: TransactionalEmailIdentifiersApi
    /** Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`. */
    message_data?: SendTransactionalEmailApiMessageData
}

export interface SendTransactionalEmailResponseApi {
    /** ID of the queued send. Delivery and engagement are reported against the template asynchronously. */
    message_id: string
    /** True when an earlier request with the same `Idempotency-Key` already queued this email. No new email was sent, and `message_id` is the earlier send's ID. */
    replayed: boolean
}

export interface TemplateSourceApi {
    /**
     * Host and path of the repository the file is in, such as `github.com/example/app`.
     * @maxLength 400
     * @nullable
     */
    repository?: string | null
    /**
     * Path of the template file in the repository, such as `emails/welcome.html`.
     * @maxLength 400
     * @nullable
     */
    path?: string | null
    /**
     * Commit or branch the file was uploaded from.
     * @maxLength 400
     * @nullable
     */
    ref?: string | null
}

export interface UploadTemplateApi {
    /**
     * Template name shown in the template library.
     * @maxLength 400
     */
    name: string
    /** Email subject line. Supports Liquid, such as `{{ variables.first_name }}`. */
    subject: string
    /** Email body as HTML, stored as sent. Supports Liquid, such as `{{ variables.first_name }}`. */
    html: string
    /** Plain-text body for email clients that can't show HTML. Leaving it out removes the stored one. */
    text?: string
    /** Inbox preview text shown after the subject. Leaving it out removes the stored one. */
    preheader?: string
    /** Set it on uploads a program makes on its own, such as a sync that may hold an older copy of the file, or an upload after a send answered `template_outdated`. When newer content already replaced this content, the upload changes nothing and answers `superseded`. The check covers the last 100 different contents the template replaced. Content outside those 100 publishes. Leave it out to publish the content in any case, such as to roll back to earlier content. */
    if_not_superseded?: boolean
    /** Set it so the upload only updates a template that code manages. When the key names a template edited in PostHog, the upload changes nothing and answers `409` with `template_edited_in_posthog`. A new key, or a template managed by code, uploads as usual. Leave it out to take over a template edited in PostHog, so code manages it from then on. */
    if_code_managed?: boolean
    /** Where the template file lives, so people in PostHog can find it. Leaving it out, or a part of it, keeps what is stored. */
    source?: TemplateSourceApi
}

/**
 * * `created` - Created
 * * `updated` - Updated
 * * `unchanged` - Unchanged
 * * `superseded` - Superseded
 */
export type TemplateUploadResultEnumApi = (typeof TemplateUploadResultEnumApi)[keyof typeof TemplateUploadResultEnumApi]

export const TemplateUploadResultEnumApi = {
    Created: 'created',
    Updated: 'updated',
    Unchanged: 'unchanged',
    Superseded: 'superseded',
} as const

export interface UploadTemplateResponseApi {
    /** ID of the template. */
    id: string
    /** Key of the template. */
    key: string
    /** `created`: the upload made a new template. `updated`: it published the uploaded content. `unchanged`: the template already had this content, so nothing was published. `superseded`: the upload set `if_not_superseded` and newer content already replaced this content, so nothing was published.
     *
     * * `created` - Created
     * * `updated` - Updated
     * * `unchanged` - Unchanged
     * * `superseded` - Superseded */
    result: TemplateUploadResultEnumApi
    /** Hash of the published content, as `v1:` and 64 hex characters. Send it with an email as `template.hash` to check PostHog holds the content you hold. After `superseded` it is the hash of the newer content. */
    content_hash: string
    /** `code` after every upload except `superseded`, which changes nothing. After `superseded` it is what the template had, which is null for a template made in PostHog that no upload claimed yet.
     *
     * * `gui` - GUI
     * * `code` - Code */
    managed_by: TemplateManagedByEnumApi | null
    /**
     * The workflow that sends this template. Each upload that changes the content writes a new version of it. Null only after `superseded`, on a template that is not transactional yet.
     * @nullable
     */
    transactional_hog_flow_id: string | null
    /** Where the template file lives, as stored after the upload. */
    source: TemplateSourceApi
}

export type MessagingCategoriesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type MessagingPreferencesExportOptOutsCsvRetrieveParams = {
    /**
     * Message category key to export. If omitted, exports recipients opted out of all marketing messages.
     */
    category_key?: string
}

export type MessagingPreferencesOptOutsRetrieveParams = {
    /**
     * Message category key to list opt-outs for. If omitted, lists recipients opted out of all marketing messages.
     */
    category_key?: string
    page?: number
    page_size?: number
    /**
     * Case-insensitive substring match on the recipient identifier.
     * @maxLength 512
     */
    search?: string
}

export type MessagingSuppressionsSuppressionsRetrieveParams = {
    page?: number
    page_size?: number
    /**
     * Case-insensitive substring match on the recipient email address.
     * @maxLength 512
     */
    search?: string
}

export type MessagingTemplatesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
