import type { AuthProject } from '@/auth/authStore'

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

export function filterProjects(projects: AuthProject[], query: string): AuthProject[] {
    const needle = query.trim().toLowerCase()
    if (!needle) {
        return projects
    }
    // Project names only, like the web app's switcher: a query that is part of an organization's name must not keep
    // every project of that organization in the list.
    return projects.filter((project) => project.name.toLowerCase().includes(needle))
}
