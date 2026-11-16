import { MCP_DOCS_URL } from './oauth-constants'

export const PROJECT_SECRET_KEY_PREFIX = 'phs_'

// The PostHog API accepts a project secret API key on these routes only (`psak_allowed_actions`
// on the business knowledge viewsets). A tool outside this list would answer 403 on every call.
export const PROJECT_SECRET_KEY_TOOLS: readonly string[] = [
    'business-knowledge-documents-search',
    'business-knowledge-document-window-retrieve',
    'business-knowledge-libraries-list',
    'business-knowledge-libraries-retrieve',
    'business-knowledge-repositories-search',
    'business-knowledge-repositories-file-retrieve',
]

export const PROJECT_SECRET_KEY_SCOPES: readonly string[] = ['business_knowledge:read']

// The API gates every route above on this flag, so a key that passed the probe is in the rollout.
export const PROJECT_SECRET_KEY_FEATURE_FLAG = 'product-business-knowledge'

export function isProjectSecretKey(token: string | undefined): boolean {
    return token?.startsWith(PROJECT_SECRET_KEY_PREFIX) === true
}

export function projectSecretKeyProbePath(projectId: string): string {
    return `/api/projects/${encodeURIComponent(projectId)}/business_knowledge/libraries/`
}

// A project secret API key has no user, so the server cannot look up a default project for it.
export function validateProjectSecretKeyProject(
    token: string | undefined,
    projectId: string | undefined
): Response | null {
    if (!isProjectSecretKey(token) || (projectId && /^\d+$/.test(projectId))) {
        return null
    }
    return new Response(
        `A project secret API key needs the ID of its project. Add ?project_id=<id> to the MCP URL, or send the x-posthog-project-id header. View the documentation for more information: ${MCP_DOCS_URL}`,
        { status: 400 }
    )
}
