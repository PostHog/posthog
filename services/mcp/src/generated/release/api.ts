/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create a release.
 */
export const ReleasesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const releasesCreateBodyNameMax = 255

export const releasesCreateBodyFeatureFlagIdsItemMax = 2147483647

export const releasesCreateBodyFeatureFlagIdsMax = 100

export const releasesCreateBodyBroadcastIdsMax = 100

export const releasesCreateBodySurveyIdsMax = 100

export const releasesCreateBodyInsightIdsItemMax = 2147483647

export const releasesCreateBodyInsightIdsMax = 100

export const releasesCreateBodyMetricInsightIdsItemMax = 2147483647

export const releasesCreateBodyMetricInsightIdsMax = 5

export const releasesCreateBodyMetricGoalsItemInsightIdMax = 2147483647

export const releasesCreateBodyMetricGoalsMax = 5

export const ReleasesCreateBody = () => zod.object({
    name: zod.string().max(releasesCreateBodyNameMax).describe('Name of the release.'),
    description: zod.string().optional().describe('What changes for the people who get the release.'),
    owner_id: zod
        .number()
        .nullish()
        .describe("ID of the user who owns the release. Must be a member of the project's organization."),
    feature_flag_ids: zod
        .array(zod.number().min(1).max(releasesCreateBodyFeatureFlagIdsItemMax))
        .max(releasesCreateBodyFeatureFlagIdsMax)
        .optional()
        .describe('IDs of the feature flags that control who gets the release, at most 100.'),
    broadcast_ids: zod
        .array(zod.string())
        .max(releasesCreateBodyBroadcastIdsMax)
        .optional()
        .describe('IDs of the broadcasts that announce the release, at most 100.'),
    survey_ids: zod
        .array(zod.string())
        .max(releasesCreateBodySurveyIdsMax)
        .optional()
        .describe('IDs of the surveys that collect feedback on the release, at most 100.'),
    insight_ids: zod
        .array(zod.number().min(1).max(releasesCreateBodyInsightIdsItemMax))
        .max(releasesCreateBodyInsightIdsMax)
        .optional()
        .describe('IDs of the saved insights that measure the release, at most 100.'),
    metric_insight_ids: zod
        .array(zod.number().min(1).max(releasesCreateBodyMetricInsightIdsItemMax))
        .max(releasesCreateBodyMetricInsightIdsMax)
        .optional()
        .describe(
            "IDs of the saved trends insights that are the release's metrics, at most 5. The first is the primary metric, the rest are secondary. Replaces the current list."
        ),
    metric_goals: zod
        .array(
            zod.object({
                insight_id: zod
                    .number()
                    .min(1)
                    .max(releasesCreateBodyMetricGoalsItemInsightIdMax)
                    .describe('ID of the metric insight the goal is for.'),
                direction: zod
                    .enum(['at_least', 'at_most'])
                    .describe('\* `at_least` - At least the target\n\* `at_most` - At most the target')
                    .describe(
                        'at_least when the metric should reach the value, at_most when it should stay at or below it.\n\n\* `at_least` - At least the target\n\* `at_most` - At most the target'
                    ),
                value: zod.number().describe('Target value of the metric.'),
            })
        )
        .max(releasesCreateBodyMetricGoalsMax)
        .optional()
        .describe(
            "Targets for the release's metrics, at most one per metric. Each insight_id must be one of the metric_insight_ids. Replaces the current goals."
        ),
})

/**
 * Get one release with its linked flags, broadcasts, surveys and insights.
 */
export const ReleasesRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Change the name, description, owner or linked flags, broadcasts, surveys and insights of a release.
 */
export const ReleasesPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const releasesPartialUpdateBodyNameMax = 255

export const releasesPartialUpdateBodyFeatureFlagIdsItemMax = 2147483647

export const releasesPartialUpdateBodyFeatureFlagIdsMax = 100

export const releasesPartialUpdateBodyBroadcastIdsMax = 100

export const releasesPartialUpdateBodySurveyIdsMax = 100

export const releasesPartialUpdateBodyInsightIdsItemMax = 2147483647

export const releasesPartialUpdateBodyInsightIdsMax = 100

export const releasesPartialUpdateBodyMetricInsightIdsItemMax = 2147483647

export const releasesPartialUpdateBodyMetricInsightIdsMax = 5

export const releasesPartialUpdateBodyMetricGoalsItemInsightIdMax = 2147483647

export const releasesPartialUpdateBodyMetricGoalsMax = 5

export const ReleasesPartialUpdateBody = () => zod.object({
    name: zod.string().max(releasesPartialUpdateBodyNameMax).optional().describe('Name of the release.'),
    description: zod.string().optional().describe('What changes for the people who get the release.'),
    owner_id: zod
        .number()
        .nullish()
        .describe("ID of the user who owns the release. Must be a member of the project's organization."),
    feature_flag_ids: zod
        .array(zod.number().min(1).max(releasesPartialUpdateBodyFeatureFlagIdsItemMax))
        .max(releasesPartialUpdateBodyFeatureFlagIdsMax)
        .optional()
        .describe('IDs of the feature flags that control who gets the release, at most 100.'),
    broadcast_ids: zod
        .array(zod.string())
        .max(releasesPartialUpdateBodyBroadcastIdsMax)
        .optional()
        .describe('IDs of the broadcasts that announce the release, at most 100.'),
    survey_ids: zod
        .array(zod.string())
        .max(releasesPartialUpdateBodySurveyIdsMax)
        .optional()
        .describe('IDs of the surveys that collect feedback on the release, at most 100.'),
    insight_ids: zod
        .array(zod.number().min(1).max(releasesPartialUpdateBodyInsightIdsItemMax))
        .max(releasesPartialUpdateBodyInsightIdsMax)
        .optional()
        .describe('IDs of the saved insights that measure the release, at most 100.'),
    metric_insight_ids: zod
        .array(zod.number().min(1).max(releasesPartialUpdateBodyMetricInsightIdsItemMax))
        .max(releasesPartialUpdateBodyMetricInsightIdsMax)
        .optional()
        .describe(
            "IDs of the saved trends insights that are the release's metrics, at most 5. The first is the primary metric, the rest are secondary. Replaces the current list."
        ),
    metric_goals: zod
        .array(
            zod.object({
                insight_id: zod
                    .number()
                    .min(1)
                    .max(releasesPartialUpdateBodyMetricGoalsItemInsightIdMax)
                    .describe('ID of the metric insight the goal is for.'),
                direction: zod
                    .enum(['at_least', 'at_most'])
                    .describe('\* `at_least` - At least the target\n\* `at_most` - At most the target')
                    .describe(
                        'at_least when the metric should reach the value, at_most when it should stay at or below it.\n\n\* `at_least` - At least the target\n\* `at_most` - At most the target'
                    ),
                value: zod.number().describe('Target value of the metric.'),
            })
        )
        .max(releasesPartialUpdateBodyMetricGoalsMax)
        .optional()
        .describe(
            "Targets for the release's metrics, at most one per metric. Each insight_id must be one of the metric_insight_ids. Replaces the current goals."
        ),
})

/**
 * Delete a release. Its flags, experiments and early access features stay.
 */
export const ReleasesDestroyParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Merge other releases into this one. This release keeps its name, gains their links, then they are deleted.
 */
export const ReleasesMergeCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const releasesMergeCreateBodyReleaseIdsMax = 100

export const releasesMergeCreateBodyNameMax = 255

export const ReleasesMergeCreateBody = () => zod.object({
    release_ids: zod
        .array(zod.string())
        .min(1)
        .max(releasesMergeCreateBodyReleaseIdsMax)
        .describe(
            'IDs of the releases to merge into this one. Their flags, broadcasts, surveys and insights move to this release, then they are deleted.'
        ),
    name: zod
        .string()
        .max(releasesMergeCreateBodyNameMax)
        .optional()
        .describe('New name for the merged release. Keeps the current name when left out.'),
})

/**
 * List the project's releases, newest or oldest first, with only the fields a list shows.
 */
export const ReleasesCatalogReleasesRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const releasesCatalogReleasesRetrieveQueryCursorDefault = ``
export const releasesCatalogReleasesRetrieveQueryCursorMax = 100

export const releasesCatalogReleasesRetrieveQueryLimitDefault = 50
export const releasesCatalogReleasesRetrieveQueryLimitMax = 100

export const releasesCatalogReleasesRetrieveQueryOrderDefault = `-created_at`

export const releasesCatalogReleasesRetrieveQueryOwnerMax = 1000

export const releasesCatalogReleasesRetrieveQuerySearchMax = 200

export const ReleasesCatalogReleasesRetrieveQueryParams = () => zod.object({
    cursor: zod
        .string()
        .max(releasesCatalogReleasesRetrieveQueryCursorMax)
        .default(releasesCatalogReleasesRetrieveQueryCursorDefault)
        .describe('next_cursor of the previous page.'),
    feature_flag_id: zod.number().min(1).optional().describe('Only releases that link this feature flag.'),
    limit: zod
        .number()
        .min(1)
        .max(releasesCatalogReleasesRetrieveQueryLimitMax)
        .default(releasesCatalogReleasesRetrieveQueryLimitDefault)
        .describe('How many releases to return, at most 100.'),
    order: zod
        .string()
        .min(1)
        .default(releasesCatalogReleasesRetrieveQueryOrderDefault)
        .describe(
            'Sort by creation time: -created_at for newest first, created_at for oldest first.\n\n\* `-created_at` - Newest first\n\* `created_at` - Oldest first'
        ),
    owner: zod
        .string()
        .max(releasesCatalogReleasesRetrieveQueryOwnerMax)
        .optional()
        .describe('Comma-separated user IDs. Only releases owned by one of them are listed.'),
    search: zod
        .string()
        .max(releasesCatalogReleasesRetrieveQuerySearchMax)
        .optional()
        .describe('Part of the release name to match.'),
})

/**
 * Find the releases a feature flag is in, and the existing releases it probably belongs to.
 */
export const ReleasesFlagSuggestionsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ReleasesFlagSuggestionsRetrieveQueryParams = () => zod.object({
    feature_flag_id: zod.number().min(1).describe('ID of the feature flag to find releases for.'),
})
