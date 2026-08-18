/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 11 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const StamphogDigestChannelsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogDigestChannelsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const StamphogDigestChannelsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogDigestChannelsCreateBody = /* @__PURE__ */ zod
    .object({
        audience_key: zod
            .string()
            .describe(
                "Opaque digest bucket this channel receives, e.g. 'repo:PostHog\/posthog'. Immutable after creation — it anchors the audience and its opt-out tombstone."
            ),
        slack_integration_id: zod.number().describe("ID of the team's Slack integration used to post the digest."),
        slack_channel_id: zod.string().describe("Slack channel ID to post the digest to, e.g. 'C012AB3CD'."),
        slack_channel_name: zod.string().optional().describe('Human-readable Slack channel name, for display only.'),
        enabled: zod.boolean().optional().describe('Whether this channel is included in the daily digest fan-out.'),
    })
    .describe('Input shape for creating\/updating a digest channel (see the repo-config write serializer).')

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const StamphogDigestChannelsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Read-only history of posted (or attempted) digests, filterable by digest channel.
 */
export const StamphogDigestRunsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogDigestRunsListQueryParams = /* @__PURE__ */ zod.object({
    digest_channel: zod.string().optional().describe('Filter by digest channel ID.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Read-only pull requests stamphog knows about, filterable by PR number and merge state.
 */
export const StamphogPullRequestsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogPullRequestsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    merged: zod
        .boolean()
        .optional()
        .describe('Filter by merge state: true for merged pull requests, false for unmerged.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    pr_number: zod.number().optional().describe('Filter by pull request number.'),
})

/**
 * Read-only pull requests stamphog knows about, filterable by PR number and merge state.
 */
export const StamphogPullRequestsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogRepoConfigsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Read-only history of stamphog review runs, filterable by repository, PR number, and status.
 */
export const StamphogReviewRunsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogReviewRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    pr_number: zod.number().optional().describe('Filter by pull request number.'),
    repository: zod.string().optional().describe("Filter by repository full name, e.g. 'PostHog\/posthog'."),
    status: zod.string().optional().describe('Filter by review run status.'),
    trigger: zod
        .enum(['all', 'label', 'self_driving'])
        .optional()
        .describe('Filter by what caused the run: self_driving, label, or all.'),
})

/**
 * Read-only history of stamphog review runs, filterable by repository, PR number, and status.
 */
export const StamphogReviewRunsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
