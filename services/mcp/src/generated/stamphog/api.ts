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
export const StamphogRepoConfigsPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const stamphogRepoConfigsPartialUpdateBodyRoutingForkLabelsMaxOne = 50

export const StamphogRepoConfigsPartialUpdateBody = () => zod
    .object({
        provider: zod
            .string()
            .optional()
            .describe(
                "SCM provider this config talks to. Defaults to 'github'. Set on create only, an update ignores it."
            ),
        repository: zod
            .string()
            .optional()
            .describe("Repository full name, e.g. 'PostHog\/posthog'. Set on create only, an update ignores it."),
        enabled: zod.boolean().optional().describe('Whether stamphog actively reviews pull requests for this repo.'),
        digest_enabled: zod
            .boolean()
            .optional()
            .describe('Whether merged PRs on this repo are captured for the daily Slack digest.'),
        review_mode: zod
            .enum(['all', 'label'])
            .describe('\* `all` - All pull requests\n\* `label` - Labeled pull requests')
            .optional()
            .describe(
                "When reviews run: 'label' reviews only pull requests carrying the trigger label (the default), mirroring the Action's opt-in flow; 'all' reviews every pull request.\n\n\* `all` - All pull requests\n\* `label` - Labeled pull requests"
            ),
        trigger_label: zod
            .string()
            .optional()
            .describe("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
        routing_mode: zod
            .enum(['off', 'always', 'fallback'])
            .describe('\* `off` - Off\n\* `always` - Always\n\* `fallback` - When stamphog does not approve')
            .optional()
            .describe(
                "When stamphog requests reviews from the code owners in the repository's owners.yaml: 'off' (the default) never; 'always' when a pull request opens ready for review or is marked ready; 'fallback' only when stamphog does not approve, where an approval requests only the owners of sensitive and new paths.\n\n\* `off` - Off\n\* `always` - Always\n\* `fallback` - When stamphog does not approve"
            ),
        routing_fork_labels: zod
            .record(zod.string(), zod.string().max(stamphogRepoConfigsPartialUpdateBodyRoutingForkLabelsMaxOne))
            .optional()
            .describe(
                "On fork pull requests, routing adds the mapped label instead of requesting a review from the team, so an outside author cannot notify it. Keys are owners.yaml team slugs such as 'team-devex', values are GitHub label names. A team with no entry gets a review request as usual. Sending the field replaces the whole map, and an empty object removes every label."
            ),
        review_on_clean_external_review: zod
            .boolean()
            .optional()
            .describe(
                "Whether a clean PostHog Review run on a pull request that opened or was marked ready starts a silent stamphog review of that head, whatever review_mode says. A silent review posts only an approval: any other verdict is stored and nothing is written to the pull request. Only for review_mode 'label' in a repository where PostHog Review runs automatic reviews: 'all' refuses it, and setting review_mode to 'all' turns it off. With routing_mode 'fallback', a head waits for that silent review before routing. Defaults to false."
            ),
    })
    .describe(
        "Input shape for creating\/updating a repo config.\n\nSeparate from the read serializer because the contract is an output shape: it carries a\nrequired id, which a create request has no way to supply. Same split as visual_review's\ninput serializers.\n\ninstallation_id is deliberately absent: it may only ever be set by the verified\nsync_installation flow, which proves the caller owns the installation before binding it. A\nclient-supplied value on this path is ignored, so a manually created config carries no\ninstallation and simply won't resolve webhooks until synced."
    )

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
 * List reviewer routing runs, newest run first by default or newest merge first with ordering=-merged_at. Each run holds its decision for every owner of the changed code: requested, cut, or not asked, with the reason, and the pull request it routed. Filter by owner to answer why a team or person was or was not asked to review. With latest_per_pr, list what landed in an owner's area. Get one run for the files each owner owns.
 */
export const StamphogRoutingRunsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const stamphogRoutingRunsListQueryHeadShaMax = 64

export const stamphogRoutingRunsListQueryLatestPerPrDefault = false

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
    latest_per_pr: zod
        .boolean()
        .default(stamphogRoutingRunsListQueryLatestPerPrDefault)
        .describe(
            "Keep only the newest run of each pull request. The newest run is picked over the pull request's whole history first, and every other filter then applies to it: a pull request whose newest run fails a filter drops out and is never replaced by an older run. With this flag, `count` counts pull requests."
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    merged: zod
        .boolean()
        .nullish()
        .describe(
            'true keeps runs of merged pull requests. false keeps runs of pull requests that are not merged: open ones and ones closed without merging, because stamphog does not record a close. Omit for both.'
        ),
    merged_after: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'Keep only runs of pull requests merged at or after this time (ISO 8601). Only merged pull requests match.'
        ),
    merged_before: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'Keep only runs of pull requests merged before this time (ISO 8601). Only merged pull requests match.'
        ),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod
        .enum(['-created_at', '-merged_at'])
        .optional()
        .describe(
            "'-created_at' (the default) lists the newest run first. '-merged_at' lists the newest merge first, then the newest run, with unmerged pull requests last.\n\n\* `-created_at` - Newest run first\n\* `-merged_at` - Newest merge first"
        ),
    outcome: zod
        .union([
            zod.enum(['requested', 'labeled', 'refused', 'cut', 'not_requested', 'already_requested']),
            zod.array(zod.enum(['requested', 'labeled', 'refused', 'cut', 'not_requested', 'already_requested'])),
        ])
        .optional()
        .describe(
            'Keep only runs where an owner got one of these outcomes. Pass one, or several as a list: a comma-separated value, a JSON-encoded array, or the repeated parameter. With `owner`, that owner must have one of them, so `owner=team-devex&outcome=cut` lists the runs that cut team-devex.'
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
