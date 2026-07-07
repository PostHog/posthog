/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AnnotationsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const annotationsCreateBodyContentMax = 8192

export const annotationsCreateBodyEmojiMax = 16

export const AnnotationsCreateBody = /* @__PURE__ */ zod
    .object({
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
            .describe('* `USR` - user\n* `GIT` - GitHub')
            .optional()
            .describe(
                'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.\n\n* `USR` - user\n* `GIT` - GitHub'
            ),
        dashboard_item: zod.number().nullish(),
        dashboard_id: zod.number().nullish(),
        deleted: zod
            .boolean()
            .optional()
            .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
        scope: zod
            .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'tag', 'recording'])
            .describe(
                '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `tag` - tag\n* `recording` - recording'
            )
            .optional()
            .describe(
                "Annotation visibility scope: `project`, `organization`, `dashboard`, `dashboard_item`, or `tag`. With `tag`, the annotation shows on every dashboard and insight carrying one of the annotation's `tags`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `tag` - tag\n* `recording` - recording"
            ),
        emoji: zod
            .string()
            .max(annotationsCreateBodyEmojiMax)
            .nullish()
            .describe(
                'Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.'
            ),
        hidden_in_user_interface: zod
            .boolean()
            .nullish()
            .describe(
                'When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.'
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe(
                'Tag names this annotation is scoped to. When `scope` is `tag`, the annotation is shown on every dashboard and insight carrying one of these tags. Required (non-empty) when `scope` is `tag`.'
            ),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const annotationsPartialUpdateBodyContentMax = 8192

export const annotationsPartialUpdateBodyEmojiMax = 16

export const AnnotationsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
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
            .describe('* `USR` - user\n* `GIT` - GitHub')
            .optional()
            .describe(
                'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.\n\n* `USR` - user\n* `GIT` - GitHub'
            ),
        dashboard_item: zod.number().nullish(),
        dashboard_id: zod.number().nullish(),
        deleted: zod
            .boolean()
            .optional()
            .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
        scope: zod
            .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'tag', 'recording'])
            .describe(
                '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `tag` - tag\n* `recording` - recording'
            )
            .optional()
            .describe(
                "Annotation visibility scope: `project`, `organization`, `dashboard`, `dashboard_item`, or `tag`. With `tag`, the annotation shows on every dashboard and insight carrying one of the annotation's `tags`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `tag` - tag\n* `recording` - recording"
            ),
        emoji: zod
            .string()
            .max(annotationsPartialUpdateBodyEmojiMax)
            .nullish()
            .describe(
                'Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.'
            ),
        hidden_in_user_interface: zod
            .boolean()
            .nullish()
            .describe(
                'When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.'
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe(
                'Tag names this annotation is scoped to. When `scope` is `tag`, the annotation is shown on every dashboard and insight carrying one of these tags. Required (non-empty) when `scope` is `tag`.'
            ),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const AnnotationsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
