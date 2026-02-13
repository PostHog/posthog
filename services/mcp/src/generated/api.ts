/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ActionsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsListQueryParams = zod.object({
    format: zod.enum(['csv', 'json']).optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const actionsListResponseResultsItemNameMax = 400

export const actionsListResponseResultsItemSlackMessageFormatMax = 1200

export const actionsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const actionsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const actionsListResponseResultsItemCreatedByOneLastNameMax = 150

export const actionsListResponseResultsItemCreatedByOneEmailMax = 254

export const actionsListResponseResultsItemIsActionDefault = true

export const ActionsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number(),
                name: zod.string().max(actionsListResponseResultsItemNameMax).nullish(),
                description: zod.string().optional(),
                tags: zod.array(zod.unknown()).optional(),
                post_to_slack: zod.boolean().optional(),
                slack_message_format: zod.string().max(actionsListResponseResultsItemSlackMessageFormatMax).optional(),
                steps: zod
                    .array(
                        zod.object({
                            event: zod.string().nullish(),
                            properties: zod.array(zod.record(zod.string(), zod.unknown())).nullish(),
                            selector: zod.string().nullish(),
                            selector_regex: zod.string().nullable(),
                            tag_name: zod.string().nullish(),
                            text: zod.string().nullish(),
                            text_matching: zod
                                .union([
                                    zod
                                        .enum(['contains', 'regex', 'exact'])
                                        .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                                    zod.literal(null),
                                ])
                                .nullish(),
                            href: zod.string().nullish(),
                            href_matching: zod
                                .union([
                                    zod
                                        .enum(['contains', 'regex', 'exact'])
                                        .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                                    zod.literal(null),
                                ])
                                .nullish(),
                            url: zod.string().nullish(),
                            url_matching: zod
                                .union([
                                    zod
                                        .enum(['contains', 'regex', 'exact'])
                                        .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                                    zod.literal(null),
                                ])
                                .nullish(),
                        })
                    )
                    .optional(),
                created_at: zod.string().datetime({}),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.string().uuid(),
                    distinct_id: zod.string().max(actionsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                    first_name: zod.string().max(actionsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                    last_name: zod.string().max(actionsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.string().email().max(actionsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
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
                }),
                deleted: zod.boolean().optional(),
                is_calculating: zod.boolean(),
                last_calculated_at: zod.string().datetime({}).optional(),
                team_id: zod.number(),
                is_action: zod.boolean(),
                bytecode_error: zod.string().nullable(),
                pinned_at: zod.string().datetime({}).nullish(),
                creation_context: zod.string(),
                _create_in_folder: zod.string().optional(),
                user_access_level: zod
                    .string()
                    .nullable()
                    .describe('The effective access level the user has for this object'),
            })
            .describe('Serializer mixin that handles tags for objects.')
    ),
})

export const ActionsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsCreateQueryParams = zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const actionsCreateBodyNameMax = 400

export const actionsCreateBodySlackMessageFormatMax = 1200

export const ActionsCreateBody = zod
    .object({
        name: zod.string().max(actionsCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod.boolean().optional(),
        slack_message_format: zod.string().max(actionsCreateBodySlackMessageFormatMax).optional(),
        steps: zod
            .array(
                zod.object({
                    event: zod.string().nullish(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).nullish(),
                    selector: zod.string().nullish(),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish(),
                    text: zod.string().nullish(),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                    href: zod.string().nullish(),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                    url: zod.string().nullish(),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
            )
            .optional(),
        deleted: zod.boolean().optional(),
        last_calculated_at: zod.string().datetime({}).optional(),
        pinned_at: zod.string().datetime({}).nullish(),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const ActionsRetrieveParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsRetrieveQueryParams = zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const actionsRetrieveResponseNameMax = 400

export const actionsRetrieveResponseSlackMessageFormatMax = 1200

export const actionsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const actionsRetrieveResponseCreatedByOneFirstNameMax = 150

export const actionsRetrieveResponseCreatedByOneLastNameMax = 150

export const actionsRetrieveResponseCreatedByOneEmailMax = 254

export const actionsRetrieveResponseIsActionDefault = true

export const ActionsRetrieveResponse = zod
    .object({
        id: zod.number(),
        name: zod.string().max(actionsRetrieveResponseNameMax).nullish(),
        description: zod.string().optional(),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod.boolean().optional(),
        slack_message_format: zod.string().max(actionsRetrieveResponseSlackMessageFormatMax).optional(),
        steps: zod
            .array(
                zod.object({
                    event: zod.string().nullish(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).nullish(),
                    selector: zod.string().nullish(),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish(),
                    text: zod.string().nullish(),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                    href: zod.string().nullish(),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                    url: zod.string().nullish(),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
            )
            .optional(),
        created_at: zod.string().datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.string().uuid(),
            distinct_id: zod.string().max(actionsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(actionsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(actionsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(actionsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
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
        }),
        deleted: zod.boolean().optional(),
        is_calculating: zod.boolean(),
        last_calculated_at: zod.string().datetime({}).optional(),
        team_id: zod.number(),
        is_action: zod.boolean(),
        bytecode_error: zod.string().nullable(),
        pinned_at: zod.string().datetime({}).nullish(),
        creation_context: zod.string(),
        _create_in_folder: zod.string().optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const ActionsPartialUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsPartialUpdateQueryParams = zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const actionsPartialUpdateBodyNameMax = 400

export const actionsPartialUpdateBodySlackMessageFormatMax = 1200

export const ActionsPartialUpdateBody = zod
    .object({
        name: zod.string().max(actionsPartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod.boolean().optional(),
        slack_message_format: zod.string().max(actionsPartialUpdateBodySlackMessageFormatMax).optional(),
        steps: zod
            .array(
                zod.object({
                    event: zod.string().nullish(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).nullish(),
                    selector: zod.string().nullish(),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish(),
                    text: zod.string().nullish(),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                    href: zod.string().nullish(),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                    url: zod.string().nullish(),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
            )
            .optional(),
        deleted: zod.boolean().optional(),
        last_calculated_at: zod.string().datetime({}).optional(),
        pinned_at: zod.string().datetime({}).nullish(),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const actionsPartialUpdateResponseNameMax = 400

export const actionsPartialUpdateResponseSlackMessageFormatMax = 1200

export const actionsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const actionsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const actionsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const actionsPartialUpdateResponseCreatedByOneEmailMax = 254

export const actionsPartialUpdateResponseIsActionDefault = true

export const ActionsPartialUpdateResponse = zod
    .object({
        id: zod.number(),
        name: zod.string().max(actionsPartialUpdateResponseNameMax).nullish(),
        description: zod.string().optional(),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod.boolean().optional(),
        slack_message_format: zod.string().max(actionsPartialUpdateResponseSlackMessageFormatMax).optional(),
        steps: zod
            .array(
                zod.object({
                    event: zod.string().nullish(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).nullish(),
                    selector: zod.string().nullish(),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish(),
                    text: zod.string().nullish(),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                    href: zod.string().nullish(),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                    url: zod.string().nullish(),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
            )
            .optional(),
        created_at: zod.string().datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.string().uuid(),
            distinct_id: zod.string().max(actionsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(actionsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(actionsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(actionsPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
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
        }),
        deleted: zod.boolean().optional(),
        is_calculating: zod.boolean(),
        last_calculated_at: zod.string().datetime({}).optional(),
        team_id: zod.number(),
        is_action: zod.boolean(),
        bytecode_error: zod.string().nullable(),
        pinned_at: zod.string().datetime({}).nullish(),
        creation_context: zod.string(),
        _create_in_folder: zod.string().optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const ActionsDestroyParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsDestroyQueryParams = zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})
