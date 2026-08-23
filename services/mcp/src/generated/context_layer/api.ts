/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Resolve a channel's wiki page
 */
export const ContextLayerChannelPagesRetrieveParams = /* @__PURE__ */ zod.object({
    channel_id: zod.string(),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Read a wiki page
 */
export const ContextLayerPagesRetrieveParams = /* @__PURE__ */ zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const ContextLayerPagesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Repo-relative Markdown path of the page to read.'),
})

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Create or replace a wiki page
 */
export const ContextLayerPagesUpdateParams = /* @__PURE__ */ zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const contextLayerPagesUpdateBodyPathMax = 512

export const contextLayerPagesUpdateBodyContentMax = 1000000

export const ContextLayerPagesUpdateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(contextLayerPagesUpdateBodyPathMax)
            .describe(
                "Repo-relative Markdown path inside the wiki's structure, for example `projects\/12\/spaces\/general.md`."
            ),
        content: zod
            .string()
            .max(contextLayerPagesUpdateBodyContentMax)
            .describe('The complete Markdown content for the page.'),
        base_head: zod
            .string()
            .nullish()
            .describe(
                'Optimistic-concurrency guard: the head sha the edit is based on. A moved head is rejected with 409 and the current head; omit to write unguarded.'
            ),
    })
    .describe('Request body for creating or replacing one wiki page.')

/**
 * The channel's page path. When the channel has no page yet, responds with the canonical path to create it at and `exists: false`.
 * @summary Resolve a channel's wiki page
 */
export const ContextLayerAgentChannelPagesRetrieveParams = /* @__PURE__ */ zod.object({
    channel_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * The same organization wiki, reached by an agent run inside a sandbox.
 *
 * This exists as a second, project-nested route because a sandbox run token
 * carries `scoped_teams`, and `APIScopePermission` accepts those only on a
 * project-nested view — on the organization-scoped route above, every sandbox
 * token is refused before it reaches any of this. The wiki is still one repo
 * per organization; the project in the path is how a run token proves which
 * organization it may act for, and is not a scope on the wiki itself.
 * @summary Read a wiki page
 */
export const ContextLayerAgentPagesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ContextLayerAgentPagesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Repo-relative Markdown path of the page to read.'),
})

/**
 * The same organization wiki, reached by an agent run inside a sandbox.
 *
 * This exists as a second, project-nested route because a sandbox run token
 * carries `scoped_teams`, and `APIScopePermission` accepts those only on a
 * project-nested view — on the organization-scoped route above, every sandbox
 * token is refused before it reaches any of this. The wiki is still one repo
 * per organization; the project in the path is how a run token proves which
 * organization it may act for, and is not a scope on the wiki itself.
 * @summary Create or replace a wiki page
 */
export const ContextLayerAgentPagesUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const contextLayerAgentPagesUpdateBodyPathMax = 512

export const contextLayerAgentPagesUpdateBodyContentMax = 1000000

export const ContextLayerAgentPagesUpdateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(contextLayerAgentPagesUpdateBodyPathMax)
            .describe(
                "Repo-relative Markdown path inside the wiki's structure, for example `projects\/12\/spaces\/general.md`."
            ),
        content: zod
            .string()
            .max(contextLayerAgentPagesUpdateBodyContentMax)
            .describe('The complete Markdown content for the page.'),
        base_head: zod
            .string()
            .nullish()
            .describe(
                'Optimistic-concurrency guard: the head sha the edit is based on. A moved head is rejected with 409 and the current head; omit to write unguarded.'
            ),
    })
    .describe('Request body for creating or replacing one wiki page.')
