import { fetchMe, fetchOrganization, type MeApi, type OrganizationApi } from '@/api/users'

export interface AuthUser {
    /** Undefined in a session persisted before the app stored it, until the next account reload. */
    id?: number
    uuid: string
    distinctId: string
    email: string
    name: string
}

export interface AuthOrganization {
    id: string
    name: string
    /** Undefined in a session persisted before the app stored it, until the next account reload. */
    aiDataProcessingApproved?: boolean
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
        user: { id: me.id, uuid: me.uuid, distinctId: me.distinct_id, email: me.email, name: displayName(me) },
        organizations: organizations.map((organization) => ({
            id: organization.id,
            name: organization.name,
            aiDataProcessingApproved: organization.is_ai_data_processing_approved === true,
        })),
        projects,
        webTeamId: me.team?.id ?? null,
    }
}

// An organization that fails to load (for example one that enforces SSO this token does not satisfy) is left out
// instead of failing sign in.
export async function loadAccount(): Promise<Account> {
    const me = await fetchMe()
    const current = me.organization
    const others = me.organizations.filter(
        (organization) => organization.is_active !== false && organization.id !== current?.id
    )
    const results = await Promise.allSettled(others.map((organization) => fetchOrganization(organization.id)))
    const loaded = results.flatMap((result) => (result.status === 'fulfilled' ? [result.value] : []))
    return buildAccount(me, current ? [current, ...loaded] : loaded)
}

export function pickProjectId(projects: AuthProject[], candidates: (number | null | undefined)[]): number | null {
    for (const candidate of candidates) {
        if (candidate !== null && candidate !== undefined && projects.some((project) => project.id === candidate)) {
            return candidate
        }
    }
    return projects[0]?.id ?? null
}
