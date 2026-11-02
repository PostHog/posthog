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
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AnnotationsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const annotationsCreateBodyContentMax = 8192

export const annotationsCreateBodyEmojiMax = 16

export const AnnotationsCreateBody = () => zod.object({
    content: zod
        .string()
        .max(annotationsCreateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('\* `USR` - user\n\* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot\/deployment notes.\n\n\* `USR` - user\n\* `GIT` - GitHub'
        ),
    dashboard_item: zod
        .number()
        .nullish()
        .describe('Optional insight ID to attach this annotation to. Must belong to the current project.'),
    dashboard_id: zod
        .number()
        .nullish()
        .describe('Optional dashboard ID to attach this annotation to. Must belong to the current project.'),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        ),
    emoji: zod
        .string()
        .max(annotationsCreateBodyEmojiMax)
        .nullish()
        .describe('Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.'),
    hidden_in_user_interface: zod
        .boolean()
        .nullish()
        .describe(
            'When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.'
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsRetrieveParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsPartialUpdateParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const annotationsPartialUpdateBodyContentMax = 8192

export const annotationsPartialUpdateBodyEmojiMax = 16

export const AnnotationsPartialUpdateBody = () => zod.object({
    content: zod
        .string()
        .max(annotationsPartialUpdateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('\* `USR` - user\n\* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot\/deployment notes.\n\n\* `USR` - user\n\* `GIT` - GitHub'
        ),
    dashboard_item: zod
        .number()
        .nullish()
        .describe('Optional insight ID to attach this annotation to. Must belong to the current project.'),
    dashboard_id: zod
        .number()
        .nullish()
        .describe('Optional dashboard ID to attach this annotation to. Must belong to the current project.'),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        ),
    emoji: zod
        .string()
        .max(annotationsPartialUpdateBodyEmojiMax)
        .nullish()
        .describe('Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.'),
    hidden_in_user_interface: zod
        .boolean()
        .nullish()
        .describe(
            'When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.'
        ),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const AnnotationsDestroyParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Lists the changes that can affect production in a time window, newest first: feature flag and experiment edits, error tracking releases, and annotations. Use it to find what changed just before an error spike or a metric drop. Changes the user has no access to are left out.
 * @summary List recent production changes
 */
export const ChangeFeedListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const changeFeedListQueryKindsDefault = []
export const changeFeedListQueryLimitDefault = 100
export const changeFeedListQueryLimitMax = 500

export const ChangeFeedListQueryParams = () => zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Start of the time window (inclusive), ISO 8601. Defaults to 24 hours before `date_to`.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('End of the time window (inclusive), ISO 8601. Defaults to now.'),
    kinds: zod
        .array(
            zod
                .enum(['feature_flag', 'experiment', 'release', 'annotation'])
                .describe(
                    '\* `feature_flag` - Feature flag\n\* `experiment` - Experiment\n\* `release` - Release\n\* `annotation` - Annotation'
                )
        )
        .default(changeFeedListQueryKindsDefault)
        .describe(
            'Return only these kinds of change. Omit to return every kind. Use `feature_flag` and `experiment` to see configuration edits without releases and annotations.'
        ),
    limit: zod
        .number()
        .min(1)
        .max(changeFeedListQueryLimitMax)
        .default(changeFeedListQueryLimitDefault)
        .describe('Maximum number of changes to return, newest first. Defaults to 100, at most 500.'),
})
