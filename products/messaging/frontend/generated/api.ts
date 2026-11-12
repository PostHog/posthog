import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    AddOptOutRequestApi,
    AddSuppressionRequestApi,
    AttachmentUploadsRequestApi,
    AttachmentUploadsResponseApi,
    BulkAddOptOutsRequestApi,
    BulkAddOptOutsResultApi,
    BulkAddSuppressionsRequestApi,
    BulkAddSuppressionsResultApi,
    BulkRemoveSuppressionsRequestApi,
    BulkRemoveSuppressionsResponseApi,
    CodeEmailApi,
    CodeEmailSourceCandidatesApi,
    EmailStatusApi,
    GenerateLinkRequestApi,
    ImportProviderOptionApi,
    MakeTransactionalApi,
    MessageCategoryApi,
    MessagePreferencesApi,
    MessageSuppressionApi,
    MessageTemplateApi,
    MessagingCategoriesListParams,
    MessagingPreferencesExportOptOutsCsvRetrieveParams,
    MessagingPreferencesOptOutsRetrieveParams,
    MessagingSuppressionsSuppressionsRetrieveParams,
    MessagingTemplatesListParams,
    PaginatedMessageCategoryListApi,
    PaginatedMessageSuppressionApi,
    PaginatedMessageTemplateListApi,
    PaginatedOptOutsApi,
    PatchedCodeEmailUpdateApi,
    PatchedDesignPatchApi,
    PatchedMessageCategoryApi,
    PatchedMessageTemplateApi,
    PatchedSupabaseAuthEmailSettingsUpdateApi,
    PreferencesLinkApi,
    ProviderImportRunApi,
    RemoveOptOutRequestApi,
    RemoveSuppressionRequestApi,
    SendEmailApi,
    SendTransactionalEmailApi,
    SendTransactionalEmailResponseApi,
    SetPreferencesApi,
    StartProviderImportApi,
    SupabaseAuthEmailSettingsApi,
    TopicPreferencesApi,
    TransactionalEmailActivityApi,
    TransactionalEmailLogDetailApi,
    TransactionalEmailLogListApi,
    TransactionalEmailLogListParams,
    TransactionalEmailLogResultsRetrieveParams,
    TransactionalEmailLogStatsOverTimeRetrieveParams,
    TransactionalEmailLogStatsRetrieveParams,
    TransactionalEmailResultsApi,
    TransactionalEmailStatsApi,
    TransactionalEmailStatsOverTimeApi,
    WebhookUrlApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getMessagingAttachmentsUploadsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging/attachments/uploads/`
}

/**
 * Before sending an email with files, ask where to upload each one. Name each file by the SHA-256 of its bytes and its size. A file this project already uploaded answers `present` and needs no upload. Any other file answers `upload`: PUT its bytes to `url` with exactly the `headers` given and without your PostHog API key, before `url_expires_at`. Once every upload succeeded, send the email with the files' hashes in `attachments`. Needs the `transactional_email:write` scope.
 * @summary Prepare attachment uploads
 */
export const messagingAttachmentsUploadsCreate = async (
    projectId: string,
    attachmentUploadsRequestApi: AttachmentUploadsRequestApi,
    options?: RequestInit
): Promise<AttachmentUploadsResponseApi> => {
    return apiMutator<AttachmentUploadsResponseApi>(getMessagingAttachmentsUploadsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(attachmentUploadsRequestApi),
    })
}

export const getMessagingEmailsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging/emails/${id}/`
}

/**
 * Get the status of one transactional email by the `message_id` that the send returned, for 30 days after the send. Needs a project secret API key with the `transactional_email:read` scope. A key with `hog_flow:read` also works, but that scope reaches the rest of Workflows too. The first status is recorded a few seconds after the send, so a read right after a send can answer 404. Treat that 404 as `queued` and read again a few seconds later.
 * @summary Get a transactional email's status
 */
export const messagingEmailsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<EmailStatusApi> => {
    return apiMutator<EmailStatusApi>(getMessagingEmailsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingPreferencesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging/preferences/`
}

/**
 * Opt one recipient out of topics, or back in, in one call. `all_marketing` applies first, then each topic in order, and the whole change is saved at once. The same change twice ends the same, but a retry that lands after a newer change undoes that change. Workflows sends skip a marketing topic the recipient opted out of. Needs a project secret API key with the `messaging_preference:write` scope, which cannot send email. A key with `hog_flow:write` also works, but that scope can send transactional email too.
 * @summary Set a recipient's topic preferences
 */
export const messagingPreferencesCreate = async (
    projectId: string,
    setPreferencesApi: SetPreferencesApi,
    options?: RequestInit
): Promise<TopicPreferencesApi> => {
    return apiMutator<TopicPreferencesApi>(getMessagingPreferencesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(setPreferencesApi),
    })
}

export const getMessagingSendEmailCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging/send/email/`
}

/**
 * Send one transactional email to one recipient. Name a template made transactional in `template_id`, and `message_data` fills its `{{ variables.* }}` placeholders. Or send content your code rendered with a `template_key`, a `subject` and `html` or `text`: PostHog sends it as is, and its metrics and run history group under the key. Transactional emails skip opt-outs and frequency caps. Send an `Idempotency-Key` header to retry safely without sending the email twice. Needs the `transactional_email:write` scope. A key with `hog_flow:write` also works, but that scope reaches the rest of Workflows too.
 * @summary Send a transactional email
 */
export const messagingSendEmailCreate = async (
    projectId: string,
    sendEmailApi: SendEmailApi,
    options?: RequestInit
): Promise<SendTransactionalEmailResponseApi> => {
    return apiMutator<SendTransactionalEmailResponseApi>(getMessagingSendEmailCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sendEmailApi),
    })
}

export const getMessagingCategoriesListUrl = (projectId: string, params?: MessagingCategoriesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/messaging_categories/?${stringifiedParams}`
        : `/api/projects/${projectId}/messaging_categories/`
}

export const messagingCategoriesList = async (
    projectId: string,
    params?: MessagingCategoriesListParams,
    options?: RequestInit
): Promise<PaginatedMessageCategoryListApi> => {
    return apiMutator<PaginatedMessageCategoryListApi>(getMessagingCategoriesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingCategoriesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_categories/`
}

export const messagingCategoriesCreate = async (
    projectId: string,
    messageCategoryApi: NonReadonly<MessageCategoryApi>,
    options?: RequestInit
): Promise<MessageCategoryApi> => {
    return apiMutator<MessageCategoryApi>(getMessagingCategoriesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageCategoryApi),
    })
}

export const getMessagingCategoriesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_categories/${id}/`
}

export const messagingCategoriesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MessageCategoryApi> => {
    return apiMutator<MessageCategoryApi>(getMessagingCategoriesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingCategoriesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_categories/${id}/`
}

export const messagingCategoriesUpdate = async (
    projectId: string,
    id: string,
    messageCategoryApi: NonReadonly<MessageCategoryApi>,
    options?: RequestInit
): Promise<MessageCategoryApi> => {
    return apiMutator<MessageCategoryApi>(getMessagingCategoriesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageCategoryApi),
    })
}

export const getMessagingCategoriesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_categories/${id}/`
}

export const messagingCategoriesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedMessageCategoryApi?: NonReadonly<PatchedMessageCategoryApi>,
    options?: RequestInit
): Promise<MessageCategoryApi> => {
    return apiMutator<MessageCategoryApi>(getMessagingCategoriesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMessageCategoryApi),
    })
}

export const getMessagingCategoriesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_categories/${id}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const messagingCategoriesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getMessagingCategoriesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getMessagingCategoriesImportFromCustomerioCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_categories/import_from_customerio/`
}

/**
 * Import subscription topics and globally unsubscribed users from Customer.io API.
 * Persists the App API key in Integration(kind="customerio-app").
 * If no app_api_key is provided, reuses the stored Integration key.
 */
export const messagingCategoriesImportFromCustomerioCreate = async (
    projectId: string,
    messageCategoryApi: NonReadonly<MessageCategoryApi>,
    options?: RequestInit
): Promise<MessageCategoryApi> => {
    return apiMutator<MessageCategoryApi>(getMessagingCategoriesImportFromCustomerioCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageCategoryApi),
    })
}

export const getMessagingCategoriesImportPreferencesCsvCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_categories/import_preferences_csv/`
}

/**
 * Import customer preferences from CSV file
 * Expected CSV columns: id, email, unsubscribed, cio_subscription_preferences
 */
export const messagingCategoriesImportPreferencesCsvCreate = async (
    projectId: string,
    messageCategoryApi: NonReadonly<MessageCategoryApi>,
    options?: RequestInit
): Promise<MessageCategoryApi> => {
    const formData = new FormData()
    formData.append(`key`, messageCategoryApi.key)
    formData.append(`name`, messageCategoryApi.name)
    if (messageCategoryApi.description !== undefined) {
        formData.append(`description`, messageCategoryApi.description)
    }
    if (messageCategoryApi.public_description !== undefined) {
        formData.append(`public_description`, messageCategoryApi.public_description)
    }
    if (messageCategoryApi.category_type !== undefined) {
        formData.append(`category_type`, messageCategoryApi.category_type)
    }
    if (messageCategoryApi.deleted !== undefined) {
        formData.append(`deleted`, messageCategoryApi.deleted.toString())
    }

    return apiMutator<MessageCategoryApi>(getMessagingCategoriesImportPreferencesCsvCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

export const getMessagingCategoriesOptoutSyncConfigRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_categories/optout_sync_config/`
}

/**
 * Get the Customer.io sync configuration state for this team.
 * Used by the frontend to derive step completion.
 */
export const messagingCategoriesOptoutSyncConfigRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<MessageCategoryApi> => {
    return apiMutator<MessageCategoryApi>(getMessagingCategoriesOptoutSyncConfigRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingCategoriesRemoveCustomerioAppConfigDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_categories/remove_customerio_app_config/`
}

/**
 * Remove the Customer.io App API integration and reset import state.
 */
export const messagingCategoriesRemoveCustomerioAppConfigDestroy = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMessagingCategoriesRemoveCustomerioAppConfigDestroyUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}

export const getMessagingCategoriesRemoveTrackConfigDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_categories/remove_track_config/`
}

/**
 * Remove the Customer.io Track API integration and reset outbound sync state.
 */
export const messagingCategoriesRemoveTrackConfigDestroy = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMessagingCategoriesRemoveTrackConfigDestroyUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}

export const getMessagingCategoriesRemoveWebhookConfigDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_categories/remove_webhook_config/`
}

/**
 * Remove the Customer.io webhook integration and reset inbound sync state.
 */
export const messagingCategoriesRemoveWebhookConfigDestroy = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMessagingCategoriesRemoveWebhookConfigDestroyUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}

export const getMessagingCategoriesSaveTrackConfigCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_categories/save_track_config/`
}

/**
 * Save Customer.io Track API credentials and/or toggle outbound sync.
 *
 * Accepts:
 *   - site_id (optional): set on first creation only
 *   - api_key (optional): set on first creation only
 *   - region (optional): "us" or "eu", set on first creation only
 *   - track_enabled (required): enable or disable outbound sync
 */
export const messagingCategoriesSaveTrackConfigCreate = async (
    projectId: string,
    messageCategoryApi: NonReadonly<MessageCategoryApi>,
    options?: RequestInit
): Promise<MessageCategoryApi> => {
    return apiMutator<MessageCategoryApi>(getMessagingCategoriesSaveTrackConfigCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageCategoryApi),
    })
}

export const getMessagingCategoriesSaveWebhookConfigCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_categories/save_webhook_config/`
}

/**
 * Save webhook signing secret and/or toggle the Customer.io webhook sync.
 *
 * Accepts:
 *   - webhook_signing_secret (optional): set on first creation only
 *   - webhook_enabled (required): enable or disable the webhook
 */
export const messagingCategoriesSaveWebhookConfigCreate = async (
    projectId: string,
    messageCategoryApi: NonReadonly<MessageCategoryApi>,
    options?: RequestInit
): Promise<MessageCategoryApi> => {
    return apiMutator<MessageCategoryApi>(getMessagingCategoriesSaveWebhookConfigCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageCategoryApi),
    })
}

export const getMessagingPreferencesAddOptOutCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_preferences/add_opt_out/`
}

/**
 * Manually add a recipient to the opt-out list for a specific category or all marketing messages.
 * @summary Manually add a recipient to the opt-out list
 */
export const messagingPreferencesAddOptOutCreate = async (
    projectId: string,
    addOptOutRequestApi: AddOptOutRequestApi,
    options?: RequestInit
): Promise<MessagePreferencesApi> => {
    return apiMutator<MessagePreferencesApi>(getMessagingPreferencesAddOptOutCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(addOptOutRequestApi),
    })
}

export const getMessagingPreferencesBulkAddOptOutsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_preferences/bulk_add_opt_outs/`
}

/**
 * Opt every recipient in the list out of the category named on their entry, or a default category.
 * @summary Add multiple recipients to the opt-out list
 */
export const messagingPreferencesBulkAddOptOutsCreate = async (
    projectId: string,
    bulkAddOptOutsRequestApi: BulkAddOptOutsRequestApi,
    options?: RequestInit
): Promise<BulkAddOptOutsResultApi> => {
    return apiMutator<BulkAddOptOutsResultApi>(getMessagingPreferencesBulkAddOptOutsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkAddOptOutsRequestApi),
    })
}

export const getMessagingPreferencesExportOptOutsCsvRetrieveUrl = (
    projectId: string,
    params?: MessagingPreferencesExportOptOutsCsvRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/messaging_preferences/export_opt_outs_csv/?${stringifiedParams}`
        : `/api/projects/${projectId}/messaging_preferences/export_opt_outs_csv/`
}

/**
 * Stream the opt-out list for a category as a CSV file that can be re-imported as-is.
 * @summary Download the opt-out list as a CSV file
 */
export const messagingPreferencesExportOptOutsCsvRetrieve = async (
    projectId: string,
    params?: MessagingPreferencesExportOptOutsCsvRetrieveParams,
    options?: RequestInit
): Promise<string> => {
    return apiMutator<string>(getMessagingPreferencesExportOptOutsCsvRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingPreferencesGenerateLinkCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_preferences/generate_link/`
}

/**
 * Generate an unsubscribe link for the current user's email address
 * @summary Generate a preferences page link for a recipient
 */
export const messagingPreferencesGenerateLinkCreate = async (
    projectId: string,
    generateLinkRequestApi?: GenerateLinkRequestApi,
    options?: RequestInit
): Promise<PreferencesLinkApi> => {
    return apiMutator<PreferencesLinkApi>(getMessagingPreferencesGenerateLinkCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(generateLinkRequestApi),
    })
}

export const getMessagingPreferencesOptOutsRetrieveUrl = (
    projectId: string,
    params?: MessagingPreferencesOptOutsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/messaging_preferences/opt_outs/?${stringifiedParams}`
        : `/api/projects/${projectId}/messaging_preferences/opt_outs/`
}

/**
 * Get opt-outs filtered by category or overall opt-outs if no category specified
 * @summary List recipients opted out of a message category
 */
export const messagingPreferencesOptOutsRetrieve = async (
    projectId: string,
    params?: MessagingPreferencesOptOutsRetrieveParams,
    options?: RequestInit
): Promise<PaginatedOptOutsApi> => {
    return apiMutator<PaginatedOptOutsApi>(getMessagingPreferencesOptOutsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingPreferencesRemoveOptOutCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_preferences/remove_opt_out/`
}

/**
 * Opt a recipient back in to a specific category, or to all marketing messages.
 * @summary Remove a recipient from the opt-out list
 */
export const messagingPreferencesRemoveOptOutCreate = async (
    projectId: string,
    removeOptOutRequestApi: RemoveOptOutRequestApi,
    options?: RequestInit
): Promise<MessagePreferencesApi> => {
    return apiMutator<MessagePreferencesApi>(getMessagingPreferencesRemoveOptOutCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(removeOptOutRequestApi),
    })
}

export const getMessagingPreferencesWebhookUrlRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_preferences/webhook_url/`
}

/**
 * Return the webhook URL for Customer.io integration setup.
 * @summary Get the Customer.io webhook URL for the team
 */
export const messagingPreferencesWebhookUrlRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<WebhookUrlApi> => {
    return apiMutator<WebhookUrlApi>(getMessagingPreferencesWebhookUrlRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingProviderImportsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_provider_imports/`
}

/**
 * Background imports from other messaging tools, such as Customer.io suppressions and global unsubscribes.
 *
 * A run executes outside the request, so a long provider list does not time out. Poll a run to show its progress.
 * @summary List the most recent provider imports
 */
export const messagingProviderImportsList = async (
    projectId: string,
    options?: RequestInit
): Promise<ProviderImportRunApi[]> => {
    return apiMutator<ProviderImportRunApi[]>(getMessagingProviderImportsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingProviderImportsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_provider_imports/`
}

/**
 * Background imports from other messaging tools, such as Customer.io suppressions and global unsubscribes.
 *
 * A run executes outside the request, so a long provider list does not time out. Poll a run to show its progress.
 * @summary Start a background import from another messaging tool
 */
export const messagingProviderImportsCreate = async (
    projectId: string,
    startProviderImportApi: StartProviderImportApi,
    options?: RequestInit
): Promise<ProviderImportRunApi> => {
    return apiMutator<ProviderImportRunApi>(getMessagingProviderImportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(startProviderImportApi),
    })
}

export const getMessagingProviderImportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_provider_imports/${id}/`
}

/**
 * Background imports from other messaging tools, such as Customer.io suppressions and global unsubscribes.
 *
 * A run executes outside the request, so a long provider list does not time out. Poll a run to show its progress.
 * @summary Get a provider import and its progress
 */
export const messagingProviderImportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ProviderImportRunApi> => {
    return apiMutator<ProviderImportRunApi>(getMessagingProviderImportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingProviderImportsProvidersListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_provider_imports/providers/`
}

/**
 * Background imports from other messaging tools, such as Customer.io suppressions and global unsubscribes.
 *
 * A run executes outside the request, so a long provider list does not time out. Poll a run to show its progress.
 * @summary List the providers and what each can import
 */
export const messagingProviderImportsProvidersList = async (
    projectId: string,
    options?: RequestInit
): Promise<ImportProviderOptionApi[]> => {
    return apiMutator<ImportProviderOptionApi[]>(getMessagingProviderImportsProvidersListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingSupabaseAuthEmailsSettingsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_supabase_auth_emails/settings/`
}

/**
 * Send a Supabase project's auth emails through transactional email templates.
 * @summary Get the Supabase auth email settings
 */
export const messagingSupabaseAuthEmailsSettingsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<SupabaseAuthEmailSettingsApi> => {
    return apiMutator<SupabaseAuthEmailSettingsApi>(getMessagingSupabaseAuthEmailsSettingsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingSupabaseAuthEmailsSettingsPartialUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_supabase_auth_emails/settings/`
}

/**
 * Send a Supabase project's auth emails through transactional email templates.
 * @summary Update the Supabase auth email settings
 */
export const messagingSupabaseAuthEmailsSettingsPartialUpdate = async (
    projectId: string,
    patchedSupabaseAuthEmailSettingsUpdateApi?: PatchedSupabaseAuthEmailSettingsUpdateApi,
    options?: RequestInit
): Promise<SupabaseAuthEmailSettingsApi> => {
    return apiMutator<SupabaseAuthEmailSettingsApi>(getMessagingSupabaseAuthEmailsSettingsPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSupabaseAuthEmailSettingsUpdateApi),
    })
}

export const getMessagingSupabaseAuthEmailsSettingsDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_supabase_auth_emails/settings/`
}

/**
 * Remove the project URL, hook secret and template mappings. The hook then refuses every call, so turn off the Send Email hook in Supabase first. The templates themselves stay.
 * @summary Disconnect the Supabase project
 */
export const messagingSupabaseAuthEmailsSettingsDestroy = async (
    projectId: string,
    options?: RequestInit
): Promise<SupabaseAuthEmailSettingsApi> => {
    return apiMutator<SupabaseAuthEmailSettingsApi>(getMessagingSupabaseAuthEmailsSettingsDestroyUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}

export const getMessagingSupabaseAuthEmailsStarterTemplatesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_supabase_auth_emails/starter_templates/`
}

/**
 * Create a transactional template for each core Supabase auth email that has no template yet, and map it. Needs a verified email sender.
 * @summary Create starter templates for the Supabase auth emails
 */
export const messagingSupabaseAuthEmailsStarterTemplatesCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<SupabaseAuthEmailSettingsApi> => {
    return apiMutator<SupabaseAuthEmailSettingsApi>(
        getMessagingSupabaseAuthEmailsStarterTemplatesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getMessagingSuppressionsAddSuppressionCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_suppressions/add_suppression/`
}

/**
 * Manually suppress an email address so no workflow sends to it.
 * @summary Manually add an email address to the suppression list
 */
export const messagingSuppressionsAddSuppressionCreate = async (
    projectId: string,
    addSuppressionRequestApi: AddSuppressionRequestApi,
    options?: RequestInit
): Promise<MessageSuppressionApi> => {
    return apiMutator<MessageSuppressionApi>(getMessagingSuppressionsAddSuppressionCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(addSuppressionRequestApi),
    })
}

export const getMessagingSuppressionsBulkAddSuppressionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_suppressions/bulk_add_suppressions/`
}

/**
 * Suppress every address in the list. Addresses that already have an entry are skipped, so repeating a call is safe.
 * @summary Add multiple email addresses to the suppression list
 */
export const messagingSuppressionsBulkAddSuppressionsCreate = async (
    projectId: string,
    bulkAddSuppressionsRequestApi: BulkAddSuppressionsRequestApi,
    options?: RequestInit
): Promise<BulkAddSuppressionsResultApi> => {
    return apiMutator<BulkAddSuppressionsResultApi>(getMessagingSuppressionsBulkAddSuppressionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkAddSuppressionsRequestApi),
    })
}

export const getMessagingSuppressionsBulkRemoveSuppressionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_suppressions/bulk_remove_suppressions/`
}

/**
 * Remove up to 100 addresses from the suppression list so they can receive messages again.
 * @summary Remove several email addresses from the suppression list
 */
export const messagingSuppressionsBulkRemoveSuppressionsCreate = async (
    projectId: string,
    bulkRemoveSuppressionsRequestApi: BulkRemoveSuppressionsRequestApi,
    options?: RequestInit
): Promise<BulkRemoveSuppressionsResponseApi> => {
    return apiMutator<BulkRemoveSuppressionsResponseApi>(
        getMessagingSuppressionsBulkRemoveSuppressionsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(bulkRemoveSuppressionsRequestApi),
        }
    )
}

export const getMessagingSuppressionsRemoveSuppressionCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_suppressions/remove_suppression/`
}

/**
 * Remove an address from the suppression list so it can receive messages again.
 * @summary Remove an email address from the suppression list
 */
export const messagingSuppressionsRemoveSuppressionCreate = async (
    projectId: string,
    removeSuppressionRequestApi: RemoveSuppressionRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMessagingSuppressionsRemoveSuppressionCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(removeSuppressionRequestApi),
    })
}

export const getMessagingSuppressionsSuppressionsRetrieveUrl = (
    projectId: string,
    params?: MessagingSuppressionsSuppressionsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/messaging_suppressions/suppressions/?${stringifiedParams}`
        : `/api/projects/${projectId}/messaging_suppressions/suppressions/`
}

/**
 * List suppressed recipients for the team, most recently updated first.
 * @summary List suppressed email addresses for the team
 */
export const messagingSuppressionsSuppressionsRetrieve = async (
    projectId: string,
    params?: MessagingSuppressionsSuppressionsRetrieveParams,
    options?: RequestInit
): Promise<PaginatedMessageSuppressionApi> => {
    return apiMutator<PaginatedMessageSuppressionApi>(
        getMessagingSuppressionsSuppressionsRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getMessagingTemplatesListUrl = (projectId: string, params?: MessagingTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/messaging_templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/messaging_templates/`
}

export const messagingTemplatesList = async (
    projectId: string,
    params?: MessagingTemplatesListParams,
    options?: RequestInit
): Promise<PaginatedMessageTemplateListApi> => {
    return apiMutator<PaginatedMessageTemplateListApi>(getMessagingTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingTemplatesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_templates/`
}

export const messagingTemplatesCreate = async (
    projectId: string,
    messageTemplateApi: NonReadonly<MessageTemplateApi>,
    options?: RequestInit
): Promise<MessageTemplateApi> => {
    return apiMutator<MessageTemplateApi>(getMessagingTemplatesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageTemplateApi),
    })
}

export const getMessagingTemplatesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_templates/${id}/`
}

export const messagingTemplatesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MessageTemplateApi> => {
    return apiMutator<MessageTemplateApi>(getMessagingTemplatesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingTemplatesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_templates/${id}/`
}

export const messagingTemplatesUpdate = async (
    projectId: string,
    id: string,
    messageTemplateApi: NonReadonly<MessageTemplateApi>,
    options?: RequestInit
): Promise<MessageTemplateApi> => {
    return apiMutator<MessageTemplateApi>(getMessagingTemplatesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageTemplateApi),
    })
}

export const getMessagingTemplatesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_templates/${id}/`
}

export const messagingTemplatesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedMessageTemplateApi?: NonReadonly<PatchedMessageTemplateApi>,
    options?: RequestInit
): Promise<MessageTemplateApi> => {
    return apiMutator<MessageTemplateApi>(getMessagingTemplatesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMessageTemplateApi),
    })
}

export const getMessagingTemplatesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_templates/${id}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const messagingTemplatesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getMessagingTemplatesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getMessagingTemplatesDesignPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_templates/${id}/design/`
}

export const messagingTemplatesDesignPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDesignPatchApi?: PatchedDesignPatchApi,
    options?: RequestInit
): Promise<MessageTemplateApi> => {
    return apiMutator<MessageTemplateApi>(getMessagingTemplatesDesignPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDesignPatchApi),
    })
}

export const getMessagingTemplatesMakeTransactionalCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_templates/${id}/make_transactional/`
}

/**
 * Make this template sendable over the transactional email API. This creates the workflow that sends it, with its own metrics, run history and versions. This can't be undone: the template stays transactional. Transactional sends ignore marketing opt-outs. Calling it again on a transactional template changes nothing. Needs the `transactional_email:write` scope, the same scope as sending. A key with `hog_flow:write` also works, but that scope reaches the rest of Workflows too. Without `hog_flow:read`, the response leaves out `content` and `draft_content`.
 * @summary Make a template transactional
 */
export const messagingTemplatesMakeTransactionalCreate = async (
    projectId: string,
    id: string,
    makeTransactionalApi?: MakeTransactionalApi,
    options?: RequestInit
): Promise<MessageTemplateApi> => {
    return apiMutator<MessageTemplateApi>(getMessagingTemplatesMakeTransactionalCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(makeTransactionalApi),
    })
}

export const getMessagingTemplatesSendCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/messaging_templates/${id}/send/`
}

/**
 * Send one transactional email from this template to one recipient. The template must be made transactional first. `message_data` fills the template's `{{ variables.* }}` placeholders. Transactional emails skip opt-outs and frequency caps. Send an `Idempotency-Key` header to retry safely without sending the email twice. Needs the `transactional_email:write` scope. A key with `hog_flow:write` also works, but that scope reaches the rest of Workflows too.
 * @summary Send a transactional email
 */
export const messagingTemplatesSendCreate = async (
    projectId: string,
    id: string,
    sendTransactionalEmailApi: SendTransactionalEmailApi,
    options?: RequestInit
): Promise<SendTransactionalEmailResponseApi> => {
    return apiMutator<SendTransactionalEmailResponseApi>(getMessagingTemplatesSendCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sendTransactionalEmailApi),
    })
}

export const getTransactionalCodeEmailsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/transactional_code_emails/`
}

/**
 * List the emails your code sends under a `template_key` that no template owns, newest first.
 * @summary List emails sent from code
 */
export const transactionalCodeEmailsList = async (
    projectId: string,
    options?: RequestInit
): Promise<CodeEmailApi[]> => {
    return apiMutator<CodeEmailApi[]>(getTransactionalCodeEmailsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTransactionalCodeEmailsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/transactional_code_emails/${id}/`
}

/**
 * @summary Get an email sent from code
 */
export const transactionalCodeEmailsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CodeEmailApi> => {
    return apiMutator<CodeEmailApi>(getTransactionalCodeEmailsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTransactionalCodeEmailsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/transactional_code_emails/${id}/`
}

/**
 * Change the description, the tags or the linked source file. The content always comes from your code, so it can't change here.
 * @summary Update an email sent from code
 */
export const transactionalCodeEmailsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCodeEmailUpdateApi?: PatchedCodeEmailUpdateApi,
    options?: RequestInit
): Promise<CodeEmailApi> => {
    return apiMutator<CodeEmailApi>(getTransactionalCodeEmailsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCodeEmailUpdateApi),
    })
}

export const getTransactionalCodeEmailsSourceCandidatesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/transactional_code_emails/${id}/source_candidates/`
}

/**
 * Search the project's connected GitHub repositories for files that use this email's key, so you can pick one to link as its source file.
 * @summary Find the file that sends an email from code
 */
export const transactionalCodeEmailsSourceCandidatesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CodeEmailSourceCandidatesApi> => {
    return apiMutator<CodeEmailSourceCandidatesApi>(
        getTransactionalCodeEmailsSourceCandidatesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getTransactionalEmailLogListUrl = (projectId: string, params?: TransactionalEmailLogListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/transactional_email_log/?${stringifiedParams}`
        : `/api/projects/${projectId}/transactional_email_log/`
}

/**
 * List the project's transactional email sends, newest first. The log keeps sends for 30 days.
 * @summary List transactional email sends
 */
export const transactionalEmailLogList = async (
    projectId: string,
    params?: TransactionalEmailLogListParams,
    options?: RequestInit
): Promise<TransactionalEmailLogListApi> => {
    return apiMutator<TransactionalEmailLogListApi>(getTransactionalEmailLogListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTransactionalEmailLogRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/transactional_email_log/${id}/`
}

/**
 * Get one send with its timeline: when it was queued, sent, delivered, opened and clicked.
 * @summary Get a transactional email send
 */
export const transactionalEmailLogRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TransactionalEmailLogDetailApi> => {
    return apiMutator<TransactionalEmailLogDetailApi>(getTransactionalEmailLogRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTransactionalEmailLogActivityRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/transactional_email_log/${id}/activity/`
}

/**
 * The recipient's events in the 7 days before and after one send, with the sessions they belong to.
 * @summary Get what a transactional email's recipient did around the send
 */
export const transactionalEmailLogActivityRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TransactionalEmailActivityApi> => {
    return apiMutator<TransactionalEmailActivityApi>(getTransactionalEmailLogActivityRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTransactionalEmailLogResultsRetrieveUrl = (
    projectId: string,
    params: TransactionalEmailLogResultsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/transactional_email_log/results/?${stringifiedParams}`
        : `/api/projects/${projectId}/transactional_email_log/results/`
}

/**
 * Of the people a transactional email was sent to, count those who did an event within a window after their first send, and add up the revenue on those events.
 * @summary Get what happened after a transactional email
 */
export const transactionalEmailLogResultsRetrieve = async (
    projectId: string,
    params: TransactionalEmailLogResultsRetrieveParams,
    options?: RequestInit
): Promise<TransactionalEmailResultsApi> => {
    return apiMutator<TransactionalEmailResultsApi>(getTransactionalEmailLogResultsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTransactionalEmailLogStatsRetrieveUrl = (
    projectId: string,
    params?: TransactionalEmailLogStatsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/transactional_email_log/stats/?${stringifiedParams}`
        : `/api/projects/${projectId}/transactional_email_log/stats/`
}

/**
 * Count sends by delivery status, opens and clicks, per template or per sending domain.
 * @summary Get transactional email delivery stats
 */
export const transactionalEmailLogStatsRetrieve = async (
    projectId: string,
    params?: TransactionalEmailLogStatsRetrieveParams,
    options?: RequestInit
): Promise<TransactionalEmailStatsApi> => {
    return apiMutator<TransactionalEmailStatsApi>(getTransactionalEmailLogStatsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTransactionalEmailLogStatsOverTimeRetrieveUrl = (
    projectId: string,
    params?: TransactionalEmailLogStatsOverTimeRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/transactional_email_log/stats_over_time/?${stringifiedParams}`
        : `/api/projects/${projectId}/transactional_email_log/stats_over_time/`
}

/**
 * Count sends by delivery status per time bucket, with totals for the period before.
 * @summary Get transactional email delivery stats over time
 */
export const transactionalEmailLogStatsOverTimeRetrieve = async (
    projectId: string,
    params?: TransactionalEmailLogStatsOverTimeRetrieveParams,
    options?: RequestInit
): Promise<TransactionalEmailStatsOverTimeApi> => {
    return apiMutator<TransactionalEmailStatsOverTimeApi>(
        getTransactionalEmailLogStatsOverTimeRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}
