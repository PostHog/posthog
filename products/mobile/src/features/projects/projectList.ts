import type { AuthProject, StoredAccount } from '@/auth/authStore'
import { orderedAccounts } from '@/features/accounts/accountLabel'

export interface OrganizationProjects {
    id: string
    name: string
    projects: AuthProject[]
}

export function groupByOrganization(projects: AuthProject[]): OrganizationProjects[] {
    const groups: OrganizationProjects[] = []
    for (const project of projects) {
        const last = groups[groups.length - 1]
        if (last && last.id === project.organizationId) {
            last.projects.push(project)
        } else {
            groups.push({ id: project.organizationId, name: project.organizationName, projects: [project] })
        }
    }
    return groups
}

export function orderSettingsProjects(projects: AuthProject[], projectId: number | null): AuthProject[] {
    const selectedOrganizationId = projects.find((project) => project.id === projectId)?.organizationId
    return groupByOrganization(projects)
        .sort((a, b) => {
            if (a.id === selectedOrganizationId) {
                return -1
            }
            if (b.id === selectedOrganizationId) {
                return 1
            }
            return a.name.localeCompare(b.name)
        })
        .flatMap((group) =>
            group.projects.sort((a, b) => {
                if (a.id === projectId) {
                    return -1
                }
                if (b.id === projectId) {
                    return 1
                }
                return a.name.localeCompare(b.name)
            })
        )
}

export function filterProjects(projects: AuthProject[], query: string): AuthProject[] {
    const needle = query.trim().toLowerCase()
    if (!needle) {
        return projects
    }
    // Project names only, like the web app's switcher: a query that is part of an organization's name must not keep
    // every project of that organization in the list.
    return projects.filter((project) => project.name.toLowerCase().includes(needle))
}

/**
 * `projects` lists the account's projects that match the query. `needs_sign_in` and `not_loaded` accounts have none on
 * this phone: the first until it signs in again, the second until it becomes active once.
 */
export type AccountSectionState = 'projects' | 'needs_sign_in' | 'not_loaded'

export interface AccountSection {
    account: StoredAccount
    active: boolean
    state: AccountSectionState
    groups: OrganizationProjects[]
    /** Organization labels show when the account has more than one, whatever the query matched. */
    showOrganizations: boolean
}

export interface AccountSections {
    sections: AccountSection[]
    /** Accounts a query skipped because none of their projects are on this phone. */
    skipped: AccountSection[]
    matches: number
}

/** The switcher's account sections: the active account first, then the others in the order they were added. */
export function accountSections(
    accounts: readonly StoredAccount[],
    activeKey: string | null,
    query: string
): AccountSections {
    const searching = query.trim() !== ''
    const sections: AccountSection[] = []
    const skipped: AccountSection[] = []
    let matches = 0
    for (const account of orderedAccounts(accounts, activeKey)) {
        const active = account.key === activeKey
        const state: AccountSectionState = account.needsSignIn
            ? 'needs_sign_in'
            : !active && account.user === null
              ? 'not_loaded'
              : 'projects'
        if (state !== 'projects') {
            const section: AccountSection = { account, active, state, groups: [], showOrganizations: false }
            if (searching) {
                skipped.push(section)
            } else {
                sections.push(section)
            }
            continue
        }
        const found = filterProjects(account.projects, query)
        matches += found.length
        if (searching && found.length === 0) {
            continue
        }
        sections.push({
            account,
            active,
            state,
            groups: groupByOrganization(found),
            showOrganizations: groupByOrganization(account.projects).length > 1,
        })
    }
    return { sections, skipped, matches }
}
