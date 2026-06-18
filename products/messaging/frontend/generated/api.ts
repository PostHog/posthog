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
    MessageCategoryApi,
    MessagePreferencesApi,
    MessageTemplateApi,
    MessagingCategoriesListParams,
    MessagingTemplatesListParams,
    PaginatedMessageCategoryListApi,
    PaginatedMessageTemplateListApi,
    PatchedDesignPatchApi,
    PatchedMessageCategoryApi,
    PatchedMessageTemplateApi,
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
 * Expected CSV columns: id, email, cio_subscription_preferences
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

export const getMessagingPreferencesGenerateLinkCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_preferences/generate_link/`
}

/**
 * Generate an unsubscribe link for the current user's email address
 */
export const messagingPreferencesGenerateLinkCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMessagingPreferencesGenerateLinkCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getMessagingPreferencesOptOutsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_preferences/opt_outs/`
}

/**
 * Get opt-outs filtered by category or overall opt-outs if no category specified
 */
export const messagingPreferencesOptOutsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getMessagingPreferencesOptOutsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingPreferencesWebhookUrlRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/messaging_preferences/webhook_url/`
}

/**
 * Return the webhook URL for Customer.io integration setup.
 */
export const messagingPreferencesWebhookUrlRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMessagingPreferencesWebhookUrlRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
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
