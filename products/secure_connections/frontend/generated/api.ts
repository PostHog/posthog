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
    SecureConnectionApprovalApi,
    SecureConnectionApprovalsApi,
    SecureConnectionEnrollmentApi,
    SecureConnectionStatusApi,
    SecureConnectionTestApi,
} from './api.schemas'

export const getSecureConnectionsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/secure_connections/`
}

/**
 * Get the secure connection status for a project.
 */
export const secureConnectionsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<SecureConnectionStatusApi> => {
    return apiMutator<SecureConnectionStatusApi>(getSecureConnectionsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getSecureConnectionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/secure_connections/`
}

/**
 * Create or replace the enrollment credential for a project's secure connection.
 */
export const secureConnectionsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<SecureConnectionEnrollmentApi> => {
    return apiMutator<SecureConnectionEnrollmentApi>(getSecureConnectionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getSecureConnectionsCdpApprovalsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/secure_connections/cdp_approvals/`
}

/**
 * List or update the secure connections approved for CDP destinations.
 */
export const secureConnectionsCdpApprovalsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<SecureConnectionApprovalsApi> => {
    return apiMutator<SecureConnectionApprovalsApi>(getSecureConnectionsCdpApprovalsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getSecureConnectionsCdpApprovalsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/secure_connections/cdp_approvals/`
}

/**
 * List or update the secure connections approved for CDP destinations.
 */
export const secureConnectionsCdpApprovalsCreate = async (
    projectId: string,
    secureConnectionApprovalApi: SecureConnectionApprovalApi,
    options?: RequestInit
): Promise<SecureConnectionApprovalsApi> => {
    return apiMutator<SecureConnectionApprovalsApi>(getSecureConnectionsCdpApprovalsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(secureConnectionApprovalApi),
    })
}

export const getSecureConnectionsTestRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/secure_connections/test/`
}

/**
 * Check whether the project has an active secure connection.
 */
export const secureConnectionsTestRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<SecureConnectionTestApi> => {
    return apiMutator<SecureConnectionTestApi>(getSecureConnectionsTestRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
