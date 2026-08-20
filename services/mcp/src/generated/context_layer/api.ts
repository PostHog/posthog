/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
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
            .describe("Repo-relative Markdown path inside the wiki's structure, for example `channels\/general.md`."),
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
