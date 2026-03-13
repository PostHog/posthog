/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AnnotationsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const annotationsListResponseResultsItemContentMax = 8192

export const annotationsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const annotationsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const annotationsListResponseResultsItemCreatedByOneLastNameMax = 150

export const annotationsListResponseResultsItemCreatedByOneEmailMax = 254

export const AnnotationsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.number().optional(),
            content: zod
                .string()
                .max(annotationsListResponseResultsItemContentMax)
                .nullish()
                .describe('Annotation text shown on charts to describe the change, release, or incident.'),
            date_marker: zod
                .string()
                .datetime({})
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
            dashboard_name: zod.string().nullish(),
            insight_short_id: zod.string().nullish(),
            insight_name: zod.string().nullish(),
            insight_derived_name: zod.string().nullish(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod
                        .string()
                        .max(annotationsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod.string().max(annotationsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                    last_name: zod.string().max(annotationsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.string().email().max(annotationsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
                .optional(),
            created_at: zod.string().datetime({}).nullish(),
            updated_at: zod.string().datetime({}).optional(),
            deleted: zod
                .boolean()
                .optional()
                .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
            scope: zod
                .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
                .describe(
                    '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
                )
                .optional()
                .describe(
                    'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
                ),
        })
    ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const annotationsCreateBodyContentMax = 8192

export const AnnotationsCreateBody = zod.object({
    content: zod
        .string()
        .max(annotationsCreateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod
        .string()
        .datetime({})
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
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsRetrieveParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const annotationsRetrieveResponseContentMax = 8192

export const annotationsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const annotationsRetrieveResponseCreatedByOneFirstNameMax = 150

export const annotationsRetrieveResponseCreatedByOneLastNameMax = 150

export const annotationsRetrieveResponseCreatedByOneEmailMax = 254

export const AnnotationsRetrieveResponse = zod.object({
    id: zod.number().optional(),
    content: zod
        .string()
        .max(annotationsRetrieveResponseContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod
        .string()
        .datetime({})
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
    dashboard_name: zod.string().nullish(),
    insight_short_id: zod.string().nullish(),
    insight_name: zod.string().nullish(),
    insight_derived_name: zod.string().nullish(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(annotationsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(annotationsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(annotationsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(annotationsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .optional(),
    created_at: zod.string().datetime({}).nullish(),
    updated_at: zod.string().datetime({}).optional(),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const annotationsUpdateBodyContentMax = 8192

export const AnnotationsUpdateBody = zod.object({
    content: zod
        .string()
        .max(annotationsUpdateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod
        .string()
        .datetime({})
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
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

export const annotationsUpdateResponseContentMax = 8192

export const annotationsUpdateResponseCreatedByOneDistinctIdMax = 200

export const annotationsUpdateResponseCreatedByOneFirstNameMax = 150

export const annotationsUpdateResponseCreatedByOneLastNameMax = 150

export const annotationsUpdateResponseCreatedByOneEmailMax = 254

export const AnnotationsUpdateResponse = zod.object({
    id: zod.number().optional(),
    content: zod
        .string()
        .max(annotationsUpdateResponseContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod
        .string()
        .datetime({})
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
    dashboard_name: zod.string().nullish(),
    insight_short_id: zod.string().nullish(),
    insight_name: zod.string().nullish(),
    insight_derived_name: zod.string().nullish(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(annotationsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(annotationsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(annotationsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(annotationsUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .optional(),
    created_at: zod.string().datetime({}).nullish(),
    updated_at: zod.string().datetime({}).optional(),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const AnnotationsPartialUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const annotationsPartialUpdateBodyContentMax = 8192

export const AnnotationsPartialUpdateBody = zod.object({
    content: zod
        .string()
        .max(annotationsPartialUpdateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod
        .string()
        .datetime({})
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
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

export const annotationsPartialUpdateResponseContentMax = 8192

export const annotationsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const annotationsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const annotationsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const annotationsPartialUpdateResponseCreatedByOneEmailMax = 254

export const AnnotationsPartialUpdateResponse = zod.object({
    id: zod.number().optional(),
    content: zod
        .string()
        .max(annotationsPartialUpdateResponseContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod
        .string()
        .datetime({})
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
    dashboard_name: zod.string().nullish(),
    insight_short_id: zod.string().nullish(),
    insight_name: zod.string().nullish(),
    insight_derived_name: zod.string().nullish(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(annotationsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(annotationsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(annotationsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(annotationsPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .optional(),
    created_at: zod.string().datetime({}).nullish(),
    updated_at: zod.string().datetime({}).optional(),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const AnnotationsDestroyParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
