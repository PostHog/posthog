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
 * Read-only history of posted (or attempted) digests, filterable by Slack channel.
 */
export const StamphogDigestRunsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogDigestRunsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    slack_channel_id: zod
        .string()
        .optional()
        .describe("Filter by the Slack channel the digest was posted to, e.g. 'C012AB3CD'."),
})

/**
 * Read-only pull requests stamphog knows about, filterable by PR number and merge state.
 */
export const StamphogPullRequestsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogPullRequestsListQueryParams = () => zod.object({
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
export const StamphogPullRequestsRetrieveParams = () => zod.object({
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
export const StamphogRepoConfigsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogRepoConfigsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsRetrieveParams = () => zod.object({
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
export const StamphogRepoConfigsDestroyParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * History of stamphog review runs, filterable by repository, PR number, and status, plus manual review requests.
 */
export const StamphogReviewRunsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogReviewRunsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    pr_number: zod.number().optional().describe('Filter by pull request number.'),
    repository: zod.string().optional().describe("Filter by repository full name, e.g. 'PostHog\/posthog'."),
    status: zod.string().optional().describe('Filter by review run status.'),
    trigger: zod
        .enum(['all', 'label', 'manual', 'reviewhog_clean', 'self_driving'])
        .optional()
        .describe(
            "Filter by what caused the run. Leave it unset to include runs from every trigger. 'all' is not a wildcard: it matches only runs in repos that review every pull request event. The other values: 'label' (the repo's trigger label opted the PR in), 'manual' (someone requested the review through the API or MCP), 'reviewhog_clean' (a clean PostHog Review run started a silent review, which posts only an approval), and 'self_driving' (stamphog reviewed a bot-authored PR from the inbox)."
        ),
})

/**
 * History of stamphog review runs, filterable by repository, PR number, and status, plus manual review requests.
 */
export const StamphogReviewRunsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StamphogReviewRunsCreateBody = () => zod
    .object({
        repository: zod
            .string()
            .describe(
                "Full name of the GitHub repository, e.g. 'PostHog\/posthog'. It must be connected and enabled in Stamphog."
            ),
        pr_number: zod.number().min(1).describe('Pull request number on GitHub.'),
    })
    .describe('Request body for asking stamphog to review one pull request.')

/**
 * History of stamphog review runs, filterable by repository, PR number, and status, plus manual review requests.
 */
export const StamphogReviewRunsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * List reviewer routing runs, newest first. Each run holds its decision for every owner of the changed code: requested, cut, or not asked, with the reason. Filter by owner to answer why a team or person was or was not asked to review. Get one run for the files each owner owns.
 */
export const StamphogRoutingRunsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const stamphogRoutingRunsListQueryHeadShaMax = 64

export const StamphogRoutingRunsListQueryParams = () => zod.object({
    created_after: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Keep only runs created at or after this time (ISO 8601).'),
    created_before: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Keep only runs created before this time (ISO 8601).'),
    head_sha: zod
        .string()
        .min(1)
        .max(stamphogRoutingRunsListQueryHeadShaMax)
        .optional()
        .describe('Keep only runs on this head commit. Pass the full 40-character SHA.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    outcome: zod
        .enum(['requested', 'labeled', 'refused', 'cut', 'not_requested', 'already_requested'])
        .optional()
        .describe(
            'Keep only runs where an owner got this outcome. With `owner`, that owner must have it, so `owner=team-devex&outcome=cut` lists the runs that cut team-devex.\n\n\* `requested` - Requested\n\* `labeled` - Labeled\n\* `refused` - Refused by GitHub\n\* `cut` - Cut\n\* `not_requested` - Not requested\n\* `already_requested` - Already requested'
        ),
    owner: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Keep only runs that decided about this owner, spelled as in owners.yaml: a team slug such as 'team-devex', or a GitHub login such as '@octocat'."
        ),
    pr_number: zod.number().optional().describe('Filter by pull request number.'),
    reason: zod
        .enum([
            'sensitive',
            'new_path',
            'largest_owner',
            'diff_not_seen',
            'cut_skipped',
            'model_kept',
            'model_cut',
            'stamphog_approved',
        ])
        .optional()
        .describe(
            'Keep only runs where an owner was kept or cut for this reason. With `owner`, that owner must have it.\n\n\* `sensitive` - Owns a sensitive path\n\* `new_path` - Owns a new path\n\* `largest_owner` - Has the largest part\n\* `diff_not_seen` - Diff not shown to the model\n\* `cut_skipped` - Cut step skipped\n\* `model_kept` - Kept by the model\n\* `model_cut` - Cut by the model\n\* `stamphog_approved` - Stamphog approved'
        ),
    repository: zod.string().min(1).optional().describe("Filter by repository full name, e.g. 'PostHog\/posthog'."),
})

/**
 * One reviewer routing run, with every changed file each owner owns.
 */
export const StamphogRoutingRunsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
