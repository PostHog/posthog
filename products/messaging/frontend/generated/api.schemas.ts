/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface AttachmentUploadFileApi {
    /**
     * SHA-256 of the file's bytes, as 64 lowercase hex characters. PostHog stores the file under it.
     * @pattern ^[0-9a-f]{64}$
     */
    sha256: string
    /**
     * Size of the file in bytes.
     * @minimum 1
     */
    size: number
}

export interface AttachmentUploadsRequestApi {
    /**
     * The files one email will carry: 1 to 10, at most 40 MB after Base64 encoding, about 29 MB of files for the whole email.
     * @minItems 1
     * @maxItems 10
     */
    files: AttachmentUploadFileApi[]
}

/**
 * * `present` - Present
 * * `upload` - Upload
 */
export type AttachmentUploadStatusEnumApi =
    (typeof AttachmentUploadStatusEnumApi)[keyof typeof AttachmentUploadStatusEnumApi]

export const AttachmentUploadStatusEnumApi = {
    Present: 'present',
    Upload: 'upload',
} as const

/**
 * For an `upload` file: the headers to send with the bytes, exactly as given. The upload is refused if the bytes don't match the size or SHA-256.
 */
export type AttachmentUploadSlotApiHeaders = { [key: string]: string }

export interface AttachmentUploadSlotApi {
    /** SHA-256 of the file, as sent. */
    sha256: string
    /** `present` when PostHog already has the file and nothing needs uploading, `upload` when the file must be uploaded to `url` before the send.
     *
     * * `present` - Present
     * * `upload` - Upload */
    status: AttachmentUploadStatusEnumApi
    /** For a `present` file: when PostHog deletes it unless a send uses it before then. */
    expires_at?: string
    /** For an `upload` file: where to send the file's bytes, without your PostHog API key. */
    url?: string
    /** For an `upload` file: the HTTP method, `PUT`. */
    method?: string
    /** For an `upload` file: the headers to send with the bytes, exactly as given. The upload is refused if the bytes don't match the size or SHA-256. */
    headers?: AttachmentUploadSlotApiHeaders
    /** For an `upload` file: when `url` stops accepting the upload. */
    url_expires_at?: string
}

export interface AttachmentUploadsResponseApi {
    /** One answer per requested file, in request order. */
    files: AttachmentUploadSlotApi[]
}

/**
 * * `scheduled` - Scheduled
 * * `queued` - Queued
 * * `canceled` - Canceled
 * * `failed` - Failed
 * * `sent` - Sent
 * * `delivered` - Delivered
 * * `bounced` - Bounced
 * * `complained` - Complained
 */
export type EmailSendStatusEnumApi = (typeof EmailSendStatusEnumApi)[keyof typeof EmailSendStatusEnumApi]

export const EmailSendStatusEnumApi = {
    Scheduled: 'scheduled',
    Queued: 'queued',
    Canceled: 'canceled',
    Failed: 'failed',
    Sent: 'sent',
    Delivered: 'delivered',
    Bounced: 'bounced',
    Complained: 'complained',
} as const

export interface EmailStatusApi {
    /** The `message_id` that the send returned. */
    id: string
    /** What happened to the email. `scheduled` means it waits for the time it was scheduled for, and `canceled` means it was canceled before it went out. `queued` means it waits to go out. `sent` means PostHog handed it to the email provider. `failed` means it was not sent, and `reason` says why. A rerun of the send can still move it to `sent`. `delivered` means the recipient's mail server accepted it. `bounced` and `complained` come later from the recipient's mail provider.
     *
     * * `scheduled` - Scheduled
     * * `queued` - Queued
     * * `canceled` - Canceled
     * * `failed` - Failed
     * * `sent` - Sent
     * * `delivered` - Delivered
     * * `bounced` - Bounced
     * * `complained` - Complained */
    status: EmailSendStatusEnumApi
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
 * Topic key to `false` to opt the recipient out of that topic, or `true` to opt them back in. Opting back in to one marketing topic after an all-marketing opt-out lifts that opt-out, so `all_marketing` becomes `true`, and keeps the other marketing topics opted out. Topics you leave out keep their current choice.
 */
export type SetPreferencesApiTopics = { [key: string]: boolean }

export interface SetPreferencesApi {
    /**
     * The recipient's email address, exactly as Workflows sends to it. Matching is exact, so `Jane@example.com` and `jane@example.com` are two recipients.
     * @maxLength 512
     */
    identifier: string
    /** `false` opts the recipient out of every marketing topic. `true` lifts that opt-out. Applied before `topics`. */
    all_marketing?: boolean
    /** Topic key to `false` to opt the recipient out of that topic, or `true` to opt them back in. Opting back in to one marketing topic after an all-marketing opt-out lifts that opt-out, so `all_marketing` becomes `true`, and keeps the other marketing topics opted out. Topics you leave out keep their current choice. */
    topics?: SetPreferencesApiTopics
}

/**
 * Topic key to `false` (opted out) or `true` (opted in), for every topic the recipient chose. A topic without a choice is not listed.
 */
export type TopicPreferencesApiTopics = { [key: string]: boolean }

export interface TopicPreferencesApi {
    /** The recipient the preferences belong to. */
    identifier: string
    /**
     * `false` when the recipient opted out of all marketing, `true` when they opted back in, `null` when they never chose.
     * @nullable
     */
    all_marketing: boolean | null
    /** Topic key to `false` (opted out) or `true` (opted in), for every topic the recipient chose. A topic without a choice is not listed. */
    topics: TopicPreferencesApiTopics
}

/**
 * Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`.
 */
export type SendEmailApiMessageData = { [key: string]: unknown }

export interface EmailAttachmentApi {
    /**
     * SHA-256 of a file uploaded through `POST /api/projects/{project_id}/messaging/attachments/uploads/`, as 64 lowercase hex characters.
     * @pattern ^[0-9a-f]{64}$
     */
    sha256: string
    /**
     * File name the recipient sees, such as `invoice.pdf`. No path and no line breaks. A file type mailbox providers block, such as `.exe`, is refused.
     * @maxLength 255
     */
    filename: string
    /**
     * MIME type of the file, such as `application/pdf`. Without it, the type follows from the file name.
     * @maxLength 78
     */
    content_type?: string
    /**
     * Content ID that the HTML body references as `cid:<content_id>` to show the file inline, such as `logo`. Without `<` or `>`.
     * @maxLength 78
     */
    content_id?: string
}

export interface SendEmailApi {
    /** Email address of the recipient. */
    to: string
    /** Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`. */
    message_data?: SendEmailApiMessageData
    /** ID of the email template to send. The template must be made transactional first. Send either `template_id` or `template_key`. */
    template_id?: string
    /**
     * Names an email whose content your code rendered, such as `order-shipped`, so its metrics, logs and status group under it. Letters, numbers, hyphens (-) and underscores (_) only, at most 256 characters. Send it with `subject` and `html` or `text`. PostHog sends the content as is and never stores it as a template.
     * @maxLength 256
     * @pattern ^[a-zA-Z0-9_-]+$
     */
    template_key?: string
    /**
     * Distinct ID of the recipient's person. The email's engagement events (sent, delivered, opened, clicked, bounced) and the send itself are recorded against that person. Defaults to the recipient's email address. The template can't read the person's properties, so pass everything it needs in `message_data`.
     * @maxLength 400
     * @nullable
     */
    distinct_id?: string | null
    /** Subject of the email your code rendered. */
    subject?: string
    /** HTML body of the email your code rendered, at most 5 MiB as UTF-8. */
    html?: string
    /** Plain text body of the email your code rendered, at most 5 MiB as UTF-8. Without it, PostHog derives the text from `html`. */
    text?: string
    /**
     * Addresses replies to the email your code rendered go to.
     * @maxItems 10
     */
    reply_to?: string[]
    /** Addresses that get a visible copy of the email your code rendered: one address, or a list of up to 10. Each is a bare address such as `jane@example.com`, with no name. Doesn't apply to a send with `template_id`, which refuses any address here. */
    cc?: string | string[] | null
    /** Addresses that get a hidden copy of the email your code rendered: one address, or a list of up to 10. Each is a bare address such as `jane@example.com`, with no name. Doesn't apply to a send with `template_id`, which refuses any address here. */
    bcc?: string | string[] | null
    /**
     * Files attached to the email your code rendered: up to 10, each uploaded first through `POST /api/projects/{project_id}/messaging/attachments/uploads/` and named here by its SHA-256. The whole email can be at most 40 MB after Base64 encoding, about 29 MB of files. File types mailbox providers block, such as `.exe`, are refused. Doesn't apply to a send with `template_id`, which refuses any file here.
     * @maxItems 10
     * @nullable
     */
    attachments?: EmailAttachmentApi[] | null
    /** When to send the email, in ISO 8601 with a timezone offset, such as `2026-11-20T09:00:00Z` or `2026-11-20T10:00:00+01:00`. PostHog holds the email until then, at most 30 days after the request. A time that already passed sends it now. Leave it out to send now. */
    scheduled_at?: string
    /** Whether the engagement events (sent, delivered, opened, clicked, bounced) of the email your code rendered are captured as analytics events of the recipient. Defaults to true. A project whose admin turned engagement capture off captures nothing, whatever the send says. */
    capture_engagement?: boolean
    /**
     * Sender of the email your code rendered, as `security@example.com` or `Example <security@example.com>`, on a verified domain of the project. Without it, the email goes out from the project's default sender, or from its only verified sender when it has no default.
     * @maxLength 1024
     */
    from?: string
}

/**
 * * `queued` - Queued
 * * `scheduled` - Scheduled
 */
export type QueuedEmailStatusEnumApi = (typeof QueuedEmailStatusEnumApi)[keyof typeof QueuedEmailStatusEnumApi]

export const QueuedEmailStatusEnumApi = {
    Queued: 'queued',
    Scheduled: 'scheduled',
} as const

export interface SendTransactionalEmailResponseApi {
    /** ID of the queued send. Delivery and engagement are reported against the template asynchronously. */
    message_id: string
    /** `scheduled` when PostHog holds the email until `scheduled_at`, and `queued` when it goes out now.
     *
     * * `queued` - Queued
     * * `scheduled` - Scheduled */
    status: QueuedEmailStatusEnumApi
    /**
     * When PostHog sends the email. Null when it goes out now.
     * @nullable
     */
    scheduled_at: string | null
    /** True when an earlier request with the same `Idempotency-Key` already queued this email. No new email was sent, and `message_id` is the earlier send's ID. */
    replayed: boolean
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

export interface BulkRemoveSuppressionsRequestApi {
    /**
     * The email addresses to remove, at most 100 per request.
     * @minItems 1
     * @maxItems 100
     * @items.maxLength 512
     */
    identifiers: string[]
    /** Set to true to remove addresses that are suppressed because the recipient reported a message as spam. Mailing them again can hurt your sender reputation. Without it, a request that includes one removes nothing and returns 400. */
    confirm_complaints?: boolean
}

export interface BulkRemoveSuppressionsResponseApi {
    /** Addresses removed from the suppression list. */
    removed: string[]
    /** Addresses that were not on the suppression list. */
    not_found: string[]
}

export interface RemoveSuppressionRequestApi {
    /**
     * The email address to remove.
     * @maxLength 512
     */
    identifier: string
    /** Set to true to remove addresses that are suppressed because the recipient reported a message as spam. Mailing them again can hurt your sender reputation. Without it, a request that includes one removes nothing and returns 400. */
    confirm_complaints?: boolean
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
    /** Whether the template has unpublished edits in `draft_content`. */
    readonly has_draft: boolean
}

export interface PaginatedMessageTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MessageTemplateApi[]
}

export interface PatchedMessageTemplateApi {
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
    /** Whether the template has unpublished edits in `draft_content`. */
    readonly has_draft?: boolean
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

export interface TransactionalEmailIdentifiersApi {
    /**
     * Distinct ID of the recipient's person. The email's engagement events (sent, delivered, opened, clicked, bounced) and the send itself are recorded against that person. Defaults to the recipient's email address. The template can't read the person's properties, so pass everything it needs in `message_data`.
     * @maxLength 400
     * @nullable
     */
    distinct_id?: string | null
}

export interface SendTransactionalEmailApi {
    /** Email address of the recipient. */
    to: string
    /** Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`. */
    message_data?: SendTransactionalEmailApiMessageData
    /** Who the email is for, used to attribute engagement events. */
    identifiers?: TransactionalEmailIdentifiersApi
}

/**
 * * `manual` - Manual
 * * `detected` - Detected from GitHub
 */
export type CodeEmailSourceOriginEnumApi =
    (typeof CodeEmailSourceOriginEnumApi)[keyof typeof CodeEmailSourceOriginEnumApi]

export const CodeEmailSourceOriginEnumApi = {
    Manual: 'manual',
    Detected: 'detected',
} as const

export interface CodeEmailApi {
    /** The code email's ID. */
    id: string
    /** The `template_key` your code sends under. Each key is one email. */
    key: string
    /** The hidden workflow that sends this key's emails. */
    hog_flow_id: string
    /** What the email is for. Empty when nobody added one. */
    description: string
    /** Tags for organizing transactional emails. */
    tags: string[]
    /** True when PostHog keeps no copy of each sent email's body and doesn't track link clicks. */
    sensitive: boolean
    /**
     * A link to the file in your repository that sends this email. Null when unlinked.
     * @nullable
     */
    source_url: string | null
    /** How `source_url` was set: `manual` when a person linked or unlinked it, `detected` when PostHog found the file in a connected GitHub repository. Setting `source_url` makes it `manual`. Null when no link was ever set or cleared.
     *
     * * `manual` - Manual
     * * `detected` - Detected from GitHub */
    readonly source_origin: CodeEmailSourceOriginEnumApi | null
    /** When your code first sent under this key. */
    created_at: string
    /**
     * Your access level to this email's workflow, such as `viewer` or `editor`. Editing the description, the tags or the source file needs `editor`.
     * @nullable
     */
    user_access_level: string | null
}

export interface PatchedCodeEmailUpdateApi {
    /**
     * What the email is for.
     * @maxLength 1000
     */
    description?: string
    /**
     * Tags for organizing transactional emails. Replaces the current tags. Send an empty list to remove them all.
     * @maxItems 10
     * @items.maxLength 255
     */
    tags?: string[]
    /** A link to the file in your repository that sends this email, such as a GitHub or GitLab file link. Must start with http:// or https://. Send null or an empty string to unlink it. */
    source_url?: string | null
}

export interface CodeEmailSourceCandidateApi {
    /** The repository that holds the file, as `owner/name`. */
    repository: string
    /** The file's path in the repository. */
    path: string
    /** The line that holds the key: the first one next to an email send call, otherwise the first match. */
    line: number
    /** A link to that line on the repository's default branch. Send it as `source_url` to link the file. */
    url: string
    /** True when the key is within five lines of an email send call, so the file most likely sends it. */
    call_site: boolean
}

export interface CodeEmailSourceCandidatesApi {
    /** One entry per file in the project's connected GitHub repositories that holds the key exactly, files with a send call first. Test, fixture and build files are left out. Empty when nothing matched or the project has no GitHub integration. */
    candidates: CodeEmailSourceCandidateApi[]
    /** False when part of the search did not finish, such as a repository GitHub could not search or a file it could not read, so a file may be missing from `candidates`. */
    complete: boolean
}

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

export interface TransactionalEmailLogEntryApi {
    /** The `message_id` that the send returned. */
    message_id: string
    /** When the send was queued. */
    created_at: string
    /** The email's delivery status. `queued` waits to go out, `sent` reached the email provider, `delivered` was accepted by the recipient's mail server, `bounced` and `complained` came back later, and `failed` was not sent.
     *
     * * `queued` - Queued
     * * `failed` - Failed
     * * `sent` - Sent
     * * `delivered` - Delivered
     * * `bounced` - Bounced
     * * `complained` - Complained */
    status: EmailDeliveryStatusEnumApi
    /** When the email reached its delivery status. */
    status_at: string
    /**
     * Why a failed email was not sent, or the bounce type. Null otherwise.
     * @nullable
     */
    reason: string | null
    /** The address the email was sent to. */
    recipient: string
    /** The workflow behind the transactional email. */
    workflow_id: string
    /**
     * The transactional email template. Null when it no longer exists.
     * @nullable
     */
    template_id: string | null
    /** The template's name. Empty when it was deleted. */
    template_name: string
    /** The domain the email was sent from. Empty before it was sent. */
    sending_domain: string
    /** Whether the recipient opened the email. */
    opened: boolean
    /** Whether the recipient clicked a link in the email. */
    clicked: boolean
}

export interface TransactionalEmailLogListApi {
    /** Sends, newest first. */
    results: TransactionalEmailLogEntryApi[]
    /** Whether another page follows. */
    has_more: boolean
}

/**
 * * `queued` - Queued
 * * `failed` - Failed
 * * `sent` - Sent
 * * `delivered` - Delivered
 * * `bounced` - Bounced
 * * `complained` - Complained
 * * `opened` - Opened
 * * `clicked` - Clicked
 */
export type EmailLogEventKindEnumApi = (typeof EmailLogEventKindEnumApi)[keyof typeof EmailLogEventKindEnumApi]

export const EmailLogEventKindEnumApi = {
    Queued: 'queued',
    Failed: 'failed',
    Sent: 'sent',
    Delivered: 'delivered',
    Bounced: 'bounced',
    Complained: 'complained',
    Opened: 'opened',
    Clicked: 'clicked',
} as const

export interface TransactionalEmailLogEventApi {
    /** What happened. The delivery statuses, plus `opened` and `clicked` for what the recipient did.
     *
     * * `queued` - Queued
     * * `failed` - Failed
     * * `sent` - Sent
     * * `delivered` - Delivered
     * * `bounced` - Bounced
     * * `complained` - Complained
     * * `opened` - Opened
     * * `clicked` - Clicked */
    kind: EmailLogEventKindEnumApi
    /** When it happened. */
    at: string
    /**
     * Why a send failed, or the bounce type. Null otherwise.
     * @nullable
     */
    reason: string | null
}

export interface TransactionalEmailLogDetailApi {
    /** The `message_id` that the send returned. */
    message_id: string
    /** When the send was queued. */
    created_at: string
    /** The email's delivery status. `queued` waits to go out, `sent` reached the email provider, `delivered` was accepted by the recipient's mail server, `bounced` and `complained` came back later, and `failed` was not sent.
     *
     * * `queued` - Queued
     * * `failed` - Failed
     * * `sent` - Sent
     * * `delivered` - Delivered
     * * `bounced` - Bounced
     * * `complained` - Complained */
    status: EmailDeliveryStatusEnumApi
    /** When the email reached its delivery status. */
    status_at: string
    /**
     * Why a failed email was not sent, or the bounce type. Null otherwise.
     * @nullable
     */
    reason: string | null
    /** The address the email was sent to. */
    recipient: string
    /** The workflow behind the transactional email. */
    workflow_id: string
    /**
     * The transactional email template. Null when it no longer exists.
     * @nullable
     */
    template_id: string | null
    /** The template's name. Empty when it was deleted. */
    template_name: string
    /** The domain the email was sent from. Empty before it was sent. */
    sending_domain: string
    /** Whether the recipient opened the email. */
    opened: boolean
    /** Whether the recipient clicked a link in the email. */
    clicked: boolean
    /** Everything that happened, oldest first. */
    timeline: TransactionalEmailLogEventApi[]
    /** The subject the email went out with. Empty when it was never sent. */
    subject: string
    /** The distinct ID the send named. Empty when it named none. */
    distinct_id: string
    /** The workflow step that sent the email, which the rendered email is stored under. Empty when no rendered email was stored. */
    action_id: string
    /** True when the template is marked sensitive, so no rendered body or subject values are kept. */
    sensitive: boolean
}

export interface TransactionalEmailActivityEventApi {
    /** The event's UUID. */
    uuid: string
    /** The event name, such as `$pageview` or a custom event. */
    event: string
    /** When the event happened. */
    timestamp: string
    /**
     * The page the person was on. Null when not set.
     * @nullable
     */
    current_url: string | null
    /**
     * The path of that page, such as `/pricing`.
     * @nullable
     */
    pathname: string | null
    /**
     * The session the event belongs to. Use it to find the session recording. Null for events captured without a session, such as server-side events.
     * @nullable
     */
    session_id: string | null
    /**
     * What an autocaptured event did, such as `click` or `submit`. Null otherwise.
     * @nullable
     */
    event_type: string | null
    /** The element an autocaptured event happened on, with its parents. Empty for other events. */
    elements_chain: string
}

export interface TransactionalEmailActivitySessionApi {
    /** The session ID, the same one session recordings use. */
    session_id: string
    /** The first event of this session in the window. */
    first_event_at: string
    /** The last event of this session in the window. */
    last_event_at: string
    /** How many of the returned events belong to this session. */
    event_count: number
    /** True when none of the session's events came before the send, so the person started it after the email. */
    started_after_send: boolean
}

export interface TransactionalEmailActivityApi {
    /** The distinct ID the send named. Empty when it named none, and then there are no events. */
    distinct_id: string
    /** When the email went to the provider, or when it was queued if it was never sent. */
    sent_at: string
    /** The person's events in the week before the send, oldest first. */
    before: TransactionalEmailActivityEventApi[]
    /** The person's events in the week after the send, oldest first. */
    after: TransactionalEmailActivityEventApi[]
    /** True when older events in the window were left out. */
    has_more_before: boolean
    /** True when later events in the window were left out. */
    has_more_after: boolean
    /** The sessions the returned events belong to, in the order they first appear. */
    sessions: TransactionalEmailActivitySessionApi[]
}

export interface TransactionalEmailResultsApi {
    /** People the email was sent to in the date range. */
    recipients: number
    /** Of those, people who did the event within the window. */
    converted: number
    /** The sum of the revenue property on those events. */
    revenue: number
    /**
     * Median hours from the first send to the first conversion. Null when none converted.
     * @nullable
     */
    median_hours_to_convert: number | null
}

export interface TransactionalEmailStatsRowApi {
    /** The template ID or the sending domain. */
    key: string
    /** The template name or the sending domain. Empty for a deleted template. */
    label: string
    /** Emails that reached the email provider. */
    sent: number
    /** Emails the recipient's mail server accepted. */
    delivered: number
    /** Emails that bounced. */
    bounced: number
    /** Emails the recipient marked as spam. */
    complained: number
    /** Emails the recipient opened. */
    opened: number
    /** Emails where the recipient clicked a link. */
    clicked: number
    /** Emails that were not sent. */
    failed: number
}

export interface TransactionalEmailStatsApi {
    /** One row per group, busiest first. */
    results: TransactionalEmailStatsRowApi[]
}

/**
 * * `minute` - Minute
 * * `hour` - Hour
 * * `day` - Day
 */
export type EmailStatsIntervalEnumApi = (typeof EmailStatsIntervalEnumApi)[keyof typeof EmailStatsIntervalEnumApi]

export const EmailStatsIntervalEnumApi = {
    Minute: 'minute',
    Hour: 'hour',
    Day: 'day',
} as const

export interface TransactionalEmailStatsCountsApi {
    /** Emails that reached the email provider. */
    sent: number
    /** Emails the recipient's mail server accepted. */
    delivered: number
    /** Emails that bounced. */
    bounced: number
    /** Emails the recipient marked as spam. */
    complained: number
    /** Emails that were not sent. */
    failed: number
}

export interface TransactionalEmailStatsBucketApi {
    /** When this time bucket starts. */
    start: string
    /** Sends queued during this bucket. */
    counts: TransactionalEmailStatsCountsApi
}

export interface TransactionalEmailStatsOverTimeApi {
    /** The width of each bucket. A `minute` bucket spans five minutes.
     *
     * * `minute` - Minute
     * * `hour` - Hour
     * * `day` - Day */
    interval: EmailStatsIntervalEnumApi
    /** The project timezone that the buckets start in. */
    timezone: string
    /** Every bucket in the period, oldest first. */
    buckets: TransactionalEmailStatsBucketApi[]
    /** Totals for the same length of time just before the period. Null when retention no longer covers it. */
    previous: TransactionalEmailStatsCountsApi | null
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
     * With true, leave out `content` and `draft_content` from each template, for lists that show names and metadata only. `has_draft` still says whether a draft exists.
     */
    basic?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * With true, list only templates sent over the transactional email API. With false, only the others. Leave out to list all templates.
     * @nullable
     */
    transactional?: boolean | null
}

export type TransactionalEmailLogListParams = {
    /**
     * Only sends queued at or after this time. Defaults to 7 days ago. The log keeps sends for 30 days.
     */
    date_from?: string
    /**
     * Only sends queued before this time. Defaults to now.
     */
    date_to?: string
    /**
     * Page size.
     * @minimum 1
     * @maximum 200
     */
    limit?: number
    /**
     * Sends to skip.
     * @minimum 0
     */
    offset?: number
    /**
     * A `message_id` for an exact match, or part of the recipient's email address.
     */
    search?: string
    /**
     * Only sends in this delivery status.
     *
     * * `queued` - Queued
     * * `failed` - Failed
     * * `sent` - Sent
     * * `delivered` - Delivered
     * * `bounced` - Bounced
     * * `complained` - Complained
     * @minLength 1
     */
    status?: TransactionalEmailLogListStatus
    /**
     * Only sends of the transactional email backed by this workflow.
     */
    workflow_id?: string
}

export type TransactionalEmailLogListStatus =
    (typeof TransactionalEmailLogListStatus)[keyof typeof TransactionalEmailLogListStatus]

export const TransactionalEmailLogListStatus = {
    Queued: 'queued',
    Failed: 'failed',
    Sent: 'sent',
    Delivered: 'delivered',
    Bounced: 'bounced',
    Complained: 'complained',
} as const

export type TransactionalEmailLogResultsRetrieveParams = {
    /**
     * Only sends queued at or after this time. Defaults to 7 days ago. The log keeps sends for 30 days.
     */
    date_from?: string
    /**
     * Only sends queued before this time. Defaults to now.
     */
    date_to?: string
    /**
     * The event that counts as a conversion, such as `signed_up`.
     * @minLength 1
     */
    event: string
    /**
     * An event property holding a revenue amount to add up.
     */
    revenue_property?: string
    /**
     * How many days after the first send the event still counts.
     * @minimum 1
     * @maximum 30
     */
    window_days?: number
    /**
     * The workflow behind the transactional email.
     */
    workflow_id: string
}

export type TransactionalEmailLogStatsRetrieveParams = {
    /**
     * Only sends queued at or after this time. Defaults to 7 days ago. The log keeps sends for 30 days.
     */
    date_from?: string
    /**
     * Only sends queued before this time. Defaults to now.
     */
    date_to?: string
    /**
     * Count per template or per sending domain.
     *
     * * `template` - Template
     * * `sending_domain` - Sending domain
     * @minLength 1
     */
    group_by?: TransactionalEmailLogStatsRetrieveGroupBy
}

export type TransactionalEmailLogStatsRetrieveGroupBy =
    (typeof TransactionalEmailLogStatsRetrieveGroupBy)[keyof typeof TransactionalEmailLogStatsRetrieveGroupBy]

export const TransactionalEmailLogStatsRetrieveGroupBy = {
    Template: 'template',
    SendingDomain: 'sending_domain',
} as const

export type TransactionalEmailLogStatsOverTimeRetrieveParams = {
    /**
     * Only sends queued at or after this time. Defaults to 7 days ago. The log keeps sends for 30 days.
     */
    date_from?: string
    /**
     * Only sends queued before this time. Defaults to now.
     */
    date_to?: string
}
