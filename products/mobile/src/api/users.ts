import { apiJson } from './client'

export interface TeamApi {
    id: number
    name: string
    project_id?: number
}

export interface OrganizationApi {
    id: string
    name: string
    teams: TeamApi[]
    /** Null means not approved, as the server treats anything but `true`. */
    is_ai_data_processing_approved?: boolean | null
    membership_level?: number | null
}

export interface OrganizationBasicApi {
    id: string
    name: string
    is_active?: boolean | null
}

export interface MeApi {
    /** The numeric user id. Some list filters, such as `tasks/?created_by=`, take it instead of the UUID. */
    id: number
    uuid: string
    distinct_id: string
    email: string
    anonymize_data?: boolean | null
    first_name: string
    last_name: string
    team: TeamApi | null
    organization: OrganizationApi | null
    organizations: OrganizationBasicApi[]
}

/** Needs `user:read`. Also the check that a new token or key works. */
export function fetchMe(init: { signal?: AbortSignal } = {}): Promise<MeApi> {
    return apiJson<MeApi>('/api/users/@me/', init)
}

/** Needs `organization:read`. */
export function fetchOrganization(
    organizationId: string,
    init: { signal?: AbortSignal } = {}
): Promise<OrganizationApi> {
    return apiJson<OrganizationApi>(`/api/organizations/${encodeURIComponent(organizationId)}/`, init)
}
