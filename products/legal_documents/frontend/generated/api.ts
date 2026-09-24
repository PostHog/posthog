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
            normalizedParams.append(key, value === null ? 'null' : String(value))
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

export const getLegalDocumentsDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/legal_documents/${id}/`
}

/**
 * Delete an unsigned legal document. The PandaDoc envelope is voided
 * first so the original signer can no longer complete it; only if that
 * succeeds is the row removed, freeing the unique-per-org-per-type
 * constraint so a fresh document can be generated.
 *
 * Returns 503 if the PandaDoc void fails — the row stays in that case
 * and the frontend should prompt the user to retry. Returns 403 for
 * signed documents (legal artifacts; staff can still delete signed
 * rows from Django admin).
 */
export const legalDocumentsDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLegalDocumentsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getLegalDocumentsDownloadRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/legal_documents/${id}/download/`
}

/**
 * Short-lived redirect to the signed PDF in object storage. 404 while the
 * envelope is still out for signature (or if the upload hasn't completed
 * yet). The underlying presigned URL expires in ~60s; clients should hit
 * this endpoint each time they want to view the PDF rather than caching.
 */
export const legalDocumentsDownloadRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getLegalDocumentsDownloadRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}
