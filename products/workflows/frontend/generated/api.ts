/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type {
    MessageCategoryApi,
    MessageTemplateApi,
    MessagingCategoriesListParams,
    MessagingTemplatesListParams,
    PaginatedMessageCategoryListApi,
    PaginatedMessageTemplateListApi,
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/messaging_categories/?${stringifiedParams}`
        : `/api/environments/${projectId}/messaging_categories/`
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
    return `/api/environments/${projectId}/messaging_categories/`
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

/**
 * Import subscription topics and globally unsubscribed users from Customer.io API
 */
export const getMessagingCategoriesImportFromCustomerioCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_categories/import_from_customerio/`
}

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

/**
 * Import customer preferences from CSV file
Expected CSV columns: id, email, cio_subscription_preferences
 */
export const getMessagingCategoriesImportPreferencesCsvCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_categories/import_preferences_csv/`
}

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

/**
 * Generate an unsubscribe link for the current user's email address
 */
export const getMessagingPreferencesGenerateLinkCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_preferences/generate_link/`
}

export const messagingPreferencesGenerateLinkCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMessagingPreferencesGenerateLinkCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

/**
 * Get opt-outs filtered by category or overall opt-outs if no category specified
 */
export const getMessagingPreferencesOptOutsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_preferences/opt_outs/`
}

export const messagingPreferencesOptOutsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getMessagingPreferencesOptOutsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMessagingTemplatesListUrl = (projectId: string, params?: MessagingTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/messaging_templates/?${stringifiedParams}`
        : `/api/environments/${projectId}/messaging_templates/`
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
    return `/api/environments/${projectId}/messaging_templates/`
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
