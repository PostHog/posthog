import type { IntegrationType } from '~/types'

import type { GitLabProjectsResponseApi } from 'products/integrations/frontend/generated/api.schemas'

// Coding tasks clone through gitlab.com only. A self-managed GitLab connection can't run a task yet.
const GITLAB_COM_HOSTNAME = 'https://gitlab.com'

export function isGitlabComIntegration(integration: IntegrationType): boolean {
    const hostname = integration.config?.hostname
    return (
        integration.kind === 'gitlab' &&
        typeof hostname === 'string' &&
        hostname.trim().replace(/\/+$/, '').toLowerCase() === GITLAB_COM_HOSTNAME
    )
}

export interface GitlabProjectsResult {
    integrationId: number
    /** `null` when the request for this connection failed. */
    response: GitLabProjectsResponseApi | null
}

export interface GitlabProjectOption {
    /** Full project path, which can be nested, such as `acme/platform/api`. */
    project: string
    integrationId: number
}

export interface CombinedGitlabProjects {
    projects: GitlabProjectOption[]
    /** Token scopes that tasks need and at least one connected token lacks. */
    missingScopes: string[]
    loadFailed: boolean
}

/**
 * Merges the project lists of all GitLab connections. When two connections list the same project, the task
 * uses the one whose token has every scope tasks need, else the first one listed.
 */
export function combineGitlabProjects(results: GitlabProjectsResult[]): CombinedGitlabProjects {
    const byProject = new Map<string, GitlabProjectOption>()
    const integrationsMissingScopes = new Set<number>()
    const missingScopes = new Set<string>()
    let loadFailed = false
    for (const { integrationId, response } of results) {
        if (!response) {
            loadFailed = true
            continue
        }
        if (response.missing_scopes.length > 0) {
            integrationsMissingScopes.add(integrationId)
        }
        response.missing_scopes.forEach((scope) => missingScopes.add(scope))
        for (const { path_with_namespace } of response.projects) {
            const key = path_with_namespace.toLowerCase()
            const existing = byProject.get(key)
            if (!existing) {
                byProject.set(key, { project: path_with_namespace, integrationId })
            } else if (integrationsMissingScopes.has(existing.integrationId) && response.missing_scopes.length === 0) {
                byProject.set(key, { ...existing, integrationId })
            }
        }
    }
    return { projects: [...byProject.values()], missingScopes: [...missingScopes], loadFailed }
}
