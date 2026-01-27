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
    EnvironmentsMessagingCategoriesListParams,
    EnvironmentsMessagingTemplatesListParams,
    MessageCategoryApi,
    MessageTemplateApi,
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

export type environmentsMessagingCategoriesListResponse200 = {
    data: PaginatedMessageCategoryListApi
    status: 200
}

export type environmentsMessagingCategoriesListResponseSuccess = environmentsMessagingCategoriesListResponse200 & {
    headers: Headers
}
export type environmentsMessagingCategoriesListResponse = environmentsMessagingCategoriesListResponseSuccess

export const getEnvironmentsMessagingCategoriesListUrl = (
    projectId: string,
    params?: EnvironmentsMessagingCategoriesListParams
) => {
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

export const environmentsMessagingCategoriesList = async (
    projectId: string,
    params?: EnvironmentsMessagingCategoriesListParams,
    options?: RequestInit
): Promise<environmentsMessagingCategoriesListResponse> => {
    return apiMutator<environmentsMessagingCategoriesListResponse>(
        getEnvironmentsMessagingCategoriesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsMessagingCategoriesCreateResponse201 = {
    data: MessageCategoryApi
    status: 201
}

export type environmentsMessagingCategoriesCreateResponseSuccess = environmentsMessagingCategoriesCreateResponse201 & {
    headers: Headers
}
export type environmentsMessagingCategoriesCreateResponse = environmentsMessagingCategoriesCreateResponseSuccess

export const getEnvironmentsMessagingCategoriesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_categories/`
}

export const environmentsMessagingCategoriesCreate = async (
    projectId: string,
    messageCategoryApi: NonReadonly<MessageCategoryApi>,
    options?: RequestInit
): Promise<environmentsMessagingCategoriesCreateResponse> => {
    return apiMutator<environmentsMessagingCategoriesCreateResponse>(
        getEnvironmentsMessagingCategoriesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(messageCategoryApi),
        }
    )
}

/**
 * Import subscription topics and globally unsubscribed users from Customer.io API
 */
export type environmentsMessagingCategoriesImportFromCustomerioCreateResponse200 = {
    data: MessageCategoryApi
    status: 200
}

export type environmentsMessagingCategoriesImportFromCustomerioCreateResponseSuccess =
    environmentsMessagingCategoriesImportFromCustomerioCreateResponse200 & {
        headers: Headers
    }
export type environmentsMessagingCategoriesImportFromCustomerioCreateResponse =
    environmentsMessagingCategoriesImportFromCustomerioCreateResponseSuccess

export const getEnvironmentsMessagingCategoriesImportFromCustomerioCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_categories/import_from_customerio/`
}

export const environmentsMessagingCategoriesImportFromCustomerioCreate = async (
    projectId: string,
    messageCategoryApi: NonReadonly<MessageCategoryApi>,
    options?: RequestInit
): Promise<environmentsMessagingCategoriesImportFromCustomerioCreateResponse> => {
    return apiMutator<environmentsMessagingCategoriesImportFromCustomerioCreateResponse>(
        getEnvironmentsMessagingCategoriesImportFromCustomerioCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(messageCategoryApi),
        }
    )
}

/**
 * Import customer preferences from CSV file
Expected CSV columns: id, email, cio_subscription_preferences
 */
export type environmentsMessagingCategoriesImportPreferencesCsvCreateResponse200 = {
    data: MessageCategoryApi
    status: 200
}

export type environmentsMessagingCategoriesImportPreferencesCsvCreateResponseSuccess =
    environmentsMessagingCategoriesImportPreferencesCsvCreateResponse200 & {
        headers: Headers
    }
export type environmentsMessagingCategoriesImportPreferencesCsvCreateResponse =
    environmentsMessagingCategoriesImportPreferencesCsvCreateResponseSuccess

export const getEnvironmentsMessagingCategoriesImportPreferencesCsvCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_categories/import_preferences_csv/`
}

export const environmentsMessagingCategoriesImportPreferencesCsvCreate = async (
    projectId: string,
    messageCategoryApi: NonReadonly<MessageCategoryApi>,
    options?: RequestInit
): Promise<environmentsMessagingCategoriesImportPreferencesCsvCreateResponse> => {
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

    return apiMutator<environmentsMessagingCategoriesImportPreferencesCsvCreateResponse>(
        getEnvironmentsMessagingCategoriesImportPreferencesCsvCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            body: formData,
        }
    )
}

/**
 * Generate an unsubscribe link for the current user's email address
 */
export type environmentsMessagingPreferencesGenerateLinkCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsMessagingPreferencesGenerateLinkCreateResponseSuccess =
    environmentsMessagingPreferencesGenerateLinkCreateResponse200 & {
        headers: Headers
    }
export type environmentsMessagingPreferencesGenerateLinkCreateResponse =
    environmentsMessagingPreferencesGenerateLinkCreateResponseSuccess

export const getEnvironmentsMessagingPreferencesGenerateLinkCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_preferences/generate_link/`
}

export const environmentsMessagingPreferencesGenerateLinkCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsMessagingPreferencesGenerateLinkCreateResponse> => {
    return apiMutator<environmentsMessagingPreferencesGenerateLinkCreateResponse>(
        getEnvironmentsMessagingPreferencesGenerateLinkCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
        }
    )
}

/**
 * Get opt-outs filtered by category or overall opt-outs if no category specified
 */
export type environmentsMessagingPreferencesOptOutsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsMessagingPreferencesOptOutsRetrieveResponseSuccess =
    environmentsMessagingPreferencesOptOutsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsMessagingPreferencesOptOutsRetrieveResponse =
    environmentsMessagingPreferencesOptOutsRetrieveResponseSuccess

export const getEnvironmentsMessagingPreferencesOptOutsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_preferences/opt_outs/`
}

export const environmentsMessagingPreferencesOptOutsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsMessagingPreferencesOptOutsRetrieveResponse> => {
    return apiMutator<environmentsMessagingPreferencesOptOutsRetrieveResponse>(
        getEnvironmentsMessagingPreferencesOptOutsRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsMessagingTemplatesListResponse200 = {
    data: PaginatedMessageTemplateListApi
    status: 200
}

export type environmentsMessagingTemplatesListResponseSuccess = environmentsMessagingTemplatesListResponse200 & {
    headers: Headers
}
export type environmentsMessagingTemplatesListResponse = environmentsMessagingTemplatesListResponseSuccess

export const getEnvironmentsMessagingTemplatesListUrl = (
    projectId: string,
    params?: EnvironmentsMessagingTemplatesListParams
) => {
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

export const environmentsMessagingTemplatesList = async (
    projectId: string,
    params?: EnvironmentsMessagingTemplatesListParams,
    options?: RequestInit
): Promise<environmentsMessagingTemplatesListResponse> => {
    return apiMutator<environmentsMessagingTemplatesListResponse>(
        getEnvironmentsMessagingTemplatesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsMessagingTemplatesCreateResponse201 = {
    data: MessageTemplateApi
    status: 201
}

export type environmentsMessagingTemplatesCreateResponseSuccess = environmentsMessagingTemplatesCreateResponse201 & {
    headers: Headers
}
export type environmentsMessagingTemplatesCreateResponse = environmentsMessagingTemplatesCreateResponseSuccess

export const getEnvironmentsMessagingTemplatesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/messaging_templates/`
}

export const environmentsMessagingTemplatesCreate = async (
    projectId: string,
    messageTemplateApi: NonReadonly<MessageTemplateApi>,
    options?: RequestInit
): Promise<environmentsMessagingTemplatesCreateResponse> => {
    return apiMutator<environmentsMessagingTemplatesCreateResponse>(
        getEnvironmentsMessagingTemplatesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(messageTemplateApi),
        }
    )
}
