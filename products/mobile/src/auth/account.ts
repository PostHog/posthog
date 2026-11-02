import { ApiError, NotSignedInError } from '@/api/client'
import { fetchMe, fetchOrganization, type MeApi, type OrganizationApi } from '@/api/users'

export interface AuthUser {
    /** Undefined in a session persisted before the app stored it, until the next account reload. */
    id?: number
    uuid: string
    distinctId: string
    email: string
    /** Unknown in older persisted sessions until the account reloads; analytics must withhold email. */
    anonymizeData?: boolean
    name: string
}

export interface AuthOrganization {
    id: string
    name: string
    /** Undefined in a session persisted before the app stored it, until the next account reload. */
    aiDataProcessingApproved?: boolean
    membershipLevel?: OrganizationApi['membership_level']
}

export interface AuthProject {
    id: number
    name: string
    organizationId: string
    organizationName: string
}

export interface Account {
    user: AuthUser
    organizations: AuthOrganization[]
    /** Grouped by organization, the user's current organization first, then by name. */
    projects: AuthProject[]
    webTeamId: number | null
}

function displayName(me: MeApi): string {
    return `${me.first_name ?? ''} ${me.last_name ?? ''}`.trim() || me.email
}

export function buildAccount(me: MeApi, organizations: OrganizationApi[]): Account {
    const projects: AuthProject[] = []
    for (const organization of organizations) {
        const teams = [...(organization.teams ?? [])].sort((a, b) => a.name.localeCompare(b.name))
        for (const team of teams) {
            projects.push({
                id: team.id,
                name: team.name,
                organizationId: organization.id,
                organizationName: organization.name,
            })
        }
    }
    return {
        user: {
            id: me.id,
            uuid: me.uuid,
            distinctId: me.distinct_id,
            email: me.email,
            anonymizeData: me.anonymize_data !== false,
            name: displayName(me),
        },
        organizations: organizations.map((organization) => ({
            id: organization.id,
            name: organization.name,
            aiDataProcessingApproved:
                organization.is_ai_data_processing_approved === undefined
                    ? undefined
                    : organization.is_ai_data_processing_approved === true,
            membershipLevel: organization.membership_level,
        })),
        projects,
        webTeamId: me.team?.id ?? null,
    }
}

// An organization that fails to load (for example one that enforces SSO this token does not satisfy) is left out
// instead of failing sign in.
async function loadAccountFrom(
    readMe: () => Promise<MeApi>,
    readOrganization: (organizationId: string) => Promise<OrganizationApi>
): Promise<Account> {
    const me = await readMe()
    const current = me.organization
    const others = me.organizations.filter(
        (organization) => organization.is_active !== false && organization.id !== current?.id
    )
    const results = await Promise.allSettled(others.map((organization) => readOrganization(organization.id)))
    const loaded = results.flatMap((result) => (result.status === 'fulfilled' ? [result.value] : []))
    return buildAccount(me, current ? [current, ...loaded] : loaded)
}

export function loadAccount(): Promise<Account> {
    return loadAccountFrom(fetchMe, fetchOrganization)
}

/** Checks a candidate sign-in without changing the active API client's host or credentials. */
export function loadAccountWithCredentials(host: string, accessToken: string): Promise<Account> {
    const read = async <T>(path: string): Promise<T> => {
        const response = await fetch(`${host}${path}`, {
            headers: { Accept: 'application/json', Authorization: `Bearer ${accessToken}` },
        })
        if (!response.ok) {
            if (response.status === 401) {
                throw new NotSignedInError()
            }
            let body: unknown
            try {
                body = await response.json()
            } catch {
                body = undefined
            }
            throw new ApiError(response.status, body, response.headers)
        }
        return (await response.json()) as T
    }
    return loadAccountFrom(
        () => read<MeApi>('/api/users/@me/'),
        (organizationId) => read<OrganizationApi>(`/api/organizations/${encodeURIComponent(organizationId)}/`)
    )
}

export function pickProjectId(projects: AuthProject[], candidates: (number | null | undefined)[]): number | null {
    for (const candidate of candidates) {
        if (candidate !== null && candidate !== undefined && projects.some((project) => project.id === candidate)) {
            return candidate
        }
    }
    return projects[0]?.id ?? null
}
