/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 12 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const AgentApplicationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Revisions for an application — read-only, nested under agent_applications.
 */
export const AgentApplicationsRevisionsListParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsRevisionsListQueryParams = /* @__PURE__ */ zod.object({
    deployment_status: zod
        .enum(['disabled', 'live', 'preview'])
        .optional()
        .describe('* `live` - live\n* `preview` - preview\n* `disabled` - disabled'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    state: zod
        .enum(['failed', 'pending_upload', 'ready', 'uploaded', 'validating'])
        .optional()
        .describe(
            '* `pending_upload` - pending_upload\n* `uploaded` - uploaded\n* `validating` - validating\n* `ready` - ready\n* `failed` - failed'
        ),
})

/**
 * Revisions for an application — read-only, nested under agent_applications.
 */
export const AgentApplicationsRevisionsRetrieveParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent application revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List sessions for an agent application (proxied from agent-janitor).
 */
export const AgentApplicationsSessionsListParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Fetch a single session by id (proxied from agent-janitor).
 */
export const AgentApplicationsSessionsRetrieveParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Cancel a running session (proxied from agent-janitor).
 */
export const AgentApplicationsSessionsCancelParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Read per-session log entries from ClickHouse.
 */
export const AgentApplicationsSessionsLogsParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const AgentApplicationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Set a revision's deployment_status to disabled. Pulls it out of any traffic role.
 */
export const AgentApplicationsDisableRevisionCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsDisableRevisionCreateBody = /* @__PURE__ */ zod.object({
    revision_id: zod
        .string()
        .describe(
            'ID of the revision to set deployment_status=disabled. Allowed from any state — use this to take a broken live or preview revision out of traffic.'
        ),
})

/**
 * PUT: replace the entire env. PATCH: merge individual keys (set to null to remove).
 */
export const AgentApplicationsEnvPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsEnvPartialUpdateBodyNameMax = 255

export const agentApplicationsEnvPartialUpdateBodySlugMax = 63

export const agentApplicationsEnvPartialUpdateBodySlugRegExp = new RegExp('^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

export const AgentApplicationsEnvPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(agentApplicationsEnvPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable display name for the application.'),
    slug: zod
        .string()
        .max(agentApplicationsEnvPartialUpdateBodySlugMax)
        .regex(agentApplicationsEnvPartialUpdateBodySlugRegExp)
        .optional()
        .describe(
            'Subdomain prefix for the application. Globally unique across all teams. Lowercase letters, digits, and hyphens only; must start and end with a letter or digit.'
        ),
    description: zod.string().optional().describe('Optional free-text description shown in the management UI.'),
})

/**
 * Mark a ready revision as preview. Blocked if required secrets are missing.
 */
export const AgentApplicationsPreviewCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsPreviewCreateBody = /* @__PURE__ */ zod.object({
    revision_id: zod
        .string()
        .describe(
            'ID of the revision to mark as preview. Must be state=ready. Multiple preview revisions can coexist; no siblings are demoted.'
        ),
})

/**
 * Promote a ready revision to live. Blocked if required secrets are missing.
 */
export const AgentApplicationsPromoteCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsPromoteCreateBody = /* @__PURE__ */ zod.object({
    revision_id: zod
        .string()
        .describe(
            'ID of the revision to promote. Must be state=ready. Any prior live revision on this application is atomically demoted to deployment_status=disabled.'
        ),
})
