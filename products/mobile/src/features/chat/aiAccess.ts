import type { ProjectScope } from '@/api/reports'
import type { AuthOrganization, AuthProject } from '@/auth/account'

/** `unknown` is a session persisted before the app stored the flag, or an organization that failed to load. */
export type OrgAiStatus = 'approved' | 'not_approved' | 'unknown'

export interface ProjectOrganization {
    name: string | null
    status: OrgAiStatus
    canApprove: boolean
}

// The chat runs in the selected project, so the approval that counts is the one of that project's organization,
// which can differ from the user's current organization on the web.
export function projectOrganization(
    organizations: readonly AuthOrganization[],
    projects: readonly AuthProject[],
    projectId: number | null
): ProjectOrganization {
    const project = projects.find((candidate) => candidate.id === projectId)
    const organization = project
        ? organizations.find((candidate) => candidate.id === project.organizationId)
        : undefined
    const approved = organization?.aiDataProcessingApproved
    return {
        name: organization?.name ?? project?.organizationName ?? null,
        status: approved === undefined ? 'unknown' : approved ? 'approved' : 'not_approved',
        canApprove: organization?.membershipLevel === 8 || organization?.membershipLevel === 15,
    }
}

/**
 * The web settings section that holds the "AI service providers" switch. The project prefix makes the web open the
 * organization of this project, not the one last used in the browser.
 */
export function orgAiSettingsUrl(scope: ProjectScope): string {
    return `${scope.host}/project/${scope.projectId}/settings/organization-details#organization-ai-consent`
}

export const PRIVACY_POLICY_URL = 'https://posthog.com/privacy'
