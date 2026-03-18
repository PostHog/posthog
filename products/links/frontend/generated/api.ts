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
import type { FileSystemApi } from './api.schemas'

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

export type environmentsFileSystemLinkCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsFileSystemLinkCreateResponseSuccess = environmentsFileSystemLinkCreateResponse200 & {
    headers: Headers
}
export type environmentsFileSystemLinkCreateResponse = environmentsFileSystemLinkCreateResponseSuccess

export const getEnvironmentsFileSystemLinkCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/file_system/${id}/link/`
}

export const environmentsFileSystemLinkCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemLinkCreateResponse> => {
    return apiMutator<environmentsFileSystemLinkCreateResponse>(getEnvironmentsFileSystemLinkCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsLinkedinAdsAccountsRetrieveResponseSuccess =
    environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse =
    environmentsIntegrationsLinkedinAdsAccountsRetrieveResponseSuccess

export const getEnvironmentsIntegrationsLinkedinAdsAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/linkedin_ads_accounts/`
}

export const environmentsIntegrationsLinkedinAdsAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse>(
        getEnvironmentsIntegrationsLinkedinAdsAccountsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponseSuccess =
    environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse =
    environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponseSuccess

export const getEnvironmentsIntegrationsLinkedinAdsConversionRulesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/linkedin_ads_conversion_rules/`
}

export const environmentsIntegrationsLinkedinAdsConversionRulesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse>(
        getEnvironmentsIntegrationsLinkedinAdsConversionRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
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

export type fileSystemLinkCreateResponse200 = {
    data: void
    status: 200
}

export type fileSystemLinkCreateResponseSuccess = fileSystemLinkCreateResponse200 & {
    headers: Headers
}
export type fileSystemLinkCreateResponse = fileSystemLinkCreateResponseSuccess

export const getFileSystemLinkCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/link/`
}

export const fileSystemLinkCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemLinkCreateResponse> => {
    return apiMutator<fileSystemLinkCreateResponse>(getFileSystemLinkCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type integrationsLinkedinAdsAccountsRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsLinkedinAdsAccountsRetrieveResponseSuccess =
    integrationsLinkedinAdsAccountsRetrieveResponse200 & {
        headers: Headers
    }
export type integrationsLinkedinAdsAccountsRetrieveResponse = integrationsLinkedinAdsAccountsRetrieveResponseSuccess

export const getIntegrationsLinkedinAdsAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_accounts/`
}

export const integrationsLinkedinAdsAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsLinkedinAdsAccountsRetrieveResponse> => {
    return apiMutator<integrationsLinkedinAdsAccountsRetrieveResponse>(
        getIntegrationsLinkedinAdsAccountsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsLinkedinAdsConversionRulesRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsLinkedinAdsConversionRulesRetrieveResponseSuccess =
    integrationsLinkedinAdsConversionRulesRetrieveResponse200 & {
        headers: Headers
    }
export type integrationsLinkedinAdsConversionRulesRetrieveResponse =
    integrationsLinkedinAdsConversionRulesRetrieveResponseSuccess

export const getIntegrationsLinkedinAdsConversionRulesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_conversion_rules/`
}

export const integrationsLinkedinAdsConversionRulesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsLinkedinAdsConversionRulesRetrieveResponse> => {
    return apiMutator<integrationsLinkedinAdsConversionRulesRetrieveResponse>(
        getIntegrationsLinkedinAdsConversionRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}
