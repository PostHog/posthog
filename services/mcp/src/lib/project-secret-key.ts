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

export const BUSINESS_KNOWLEDGE_PATH = '/mcp/business-knowledge'

// `@current` resolves to the key's own project, so the key is the only thing a caller sends.
export const PROJECT_SECRET_KEY_ACCESS_PATH = '/api/projects/@current/business_knowledge/access/'

export const PROJECT_SECRET_KEY_REMEDIATION =
    'This project secret API key cannot read business knowledge. To fix: in PostHog, open the business knowledge settings in the project that owns the knowledge, and create a key under "Connect your agent".'

export function isBusinessKnowledgePath(pathname: string): boolean {
    return pathname === BUSINESS_KNOWLEDGE_PATH || pathname.startsWith(`${BUSINESS_KNOWLEDGE_PATH}/`)
}

// `/mcp` refuses a project secret API key, and the business knowledge path refuses every other credential.
export function validateCredentialForPath(token: string | undefined, request: Request): Response | null {
    const url = new URL(request.url)
    const onKnowledgePath = isBusinessKnowledgePath(url.pathname)
    if (onKnowledgePath && !isProjectSecretKey(token)) {
        return new Response(
            `This URL needs a project secret API key (phs_...) with the business_knowledge:read scope in the Authorization header. View the documentation for more information: ${MCP_DOCS_URL}`,
            { status: 401 }
        )
    }
    if (!onKnowledgePath && isProjectSecretKey(token)) {
        url.pathname = BUSINESS_KNOWLEDGE_PATH
        url.search = ''
        return new Response(
            `A project secret API key connects to ${url.toString()}. Change the MCP URL and try again. View the documentation for more information: ${MCP_DOCS_URL}`,
            { status: 400 }
        )
    }
    return null
}
