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
    CreateLegalDocumentApi,
    LegalDocumentDTOApi,
    LegalDocumentsListParams,
    PaginatedLegalDocumentDTOListApi,
} from './api.schemas'

export const getLegalDocumentsListUrl = (organizationId: string, params?: LegalDocumentsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/legal_documents/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/legal_documents/`
}

export const legalDocumentsList = async (
    organizationId: string,
    params?: LegalDocumentsListParams,
    options?: RequestInit
): Promise<PaginatedLegalDocumentDTOListApi> => {
    return apiMutator<PaginatedLegalDocumentDTOListApi>(getLegalDocumentsListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLegalDocumentsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/legal_documents/`
}

export const legalDocumentsCreate = async (
    organizationId: string,
    createLegalDocumentApi: CreateLegalDocumentApi,
    options?: RequestInit
): Promise<LegalDocumentDTOApi> => {
    return apiMutator<LegalDocumentDTOApi>(getLegalDocumentsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createLegalDocumentApi),
    })
}

export const getLegalDocumentsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/legal_documents/${id}/`
}

export const legalDocumentsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<LegalDocumentDTOApi> => {
    return apiMutator<LegalDocumentDTOApi>(getLegalDocumentsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}
