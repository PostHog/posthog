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
}

export interface OrganizationBasicApi {
    id: string
    name: string
    is_active?: boolean | null
}

export interface MeApi {
    uuid: string
    distinct_id: string
    email: string
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
export function fetchOrganization(organizationId: string): Promise<OrganizationApi> {
    return apiJson<OrganizationApi>(`/api/organizations/${encodeURIComponent(organizationId)}/`)
}
