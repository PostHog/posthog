/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 ops
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

export const actionsListResponseResultsItemStepsItemPropertiesItemOperatorDefault = `exact`
export const actionsListResponseResultsItemStepsItemPropertiesItemTypeDefault = `event`
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
                name: zod
                    .string()
                    .max(actionsListResponseResultsItemNameMax)
                    .nullish()
                    .describe('Name of the action (must be unique within the project).'),
                description: zod
                    .string()
                    .optional()
                    .describe('Human-readable description of what this action represents.'),
                tags: zod.array(zod.unknown()).optional(),
                post_to_slack: zod
                    .boolean()
                    .optional()
                    .describe('Whether to post a notification to Slack when this action is triggered.'),
                slack_message_format: zod
                    .string()
                    .max(actionsListResponseResultsItemSlackMessageFormatMax)
                    .optional()
                    .describe('Custom Slack message format. Supports templates with event properties.'),
                steps: zod
                    .array(
                        zod.object({
                            event: zod
                                .string()
                                .nullish()
                                .describe(
                                    "Event name to match (e.g. '$pageview', '$autocapture', or a custom event name)."
                                ),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`"
                                            ),
                                        value: zod
                                            .union([
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.array(zod.union([zod.string(), zod.number()])),
                                            ])
                                            .describe(
                                                'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`'
                                            ),
                                        operator: zod
                                            .union([
                                                zod
                                                    .enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'lt',
                                                        'gte',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_after',
                                                        'is_date_before',
                                                        'in',
                                                        'not_in',
                                                    ])
                                                    .describe(
                                                        '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                                                    ),
                                                zod.enum(['']),
                                                zod.literal(null),
                                            ])
                                            .default(
                                                actionsListResponseResultsItemStepsItemPropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .union([
                                                zod
                                                    .enum([
                                                        'event',
                                                        'event_metadata',
                                                        'feature',
                                                        'person',
                                                        'cohort',
                                                        'element',
                                                        'static-cohort',
                                                        'dynamic-cohort',
                                                        'precalculated-cohort',
                                                        'group',
                                                        'recording',
                                                        'log_entry',
                                                        'behavioral',
                                                        'session',
                                                        'hogql',
                                                        'data_warehouse',
                                                        'data_warehouse_person_property',
                                                        'error_tracking_issue',
                                                        'log',
                                                        'log_attribute',
                                                        'log_resource_attribute',
                                                        'revenue_analytics',
                                                        'flag',
                                                        'workflow_variable',
                                                    ])
                                                    .describe(
                                                        '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                                    ),
                                                zod.enum(['']),
                                            ])
                                            .default(actionsListResponseResultsItemStepsItemPropertiesItemTypeDefault),
                                    })
                                )
                                .nullish()
                                .describe(
                                    "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
                                ),
                            selector: zod
                                .string()
                                .nullish()
                                .describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
                            selector_regex: zod.string().nullable(),
                            tag_name: zod
                                .string()
                                .nullish()
                                .describe('HTML tag name to match (e.g. "button", "a", "input").'),
                            text: zod.string().nullish().describe('Element text content to match.'),
                            text_matching: zod
                                .union([
                                    zod
                                        .enum(['contains', 'regex', 'exact'])
                                        .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                                    zod.literal(null),
                                ])
                                .nullish()
                                .describe(
                                    'How to match the text value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                                ),
                            href: zod.string().nullish().describe('Link href attribute to match.'),
                            href_matching: zod
                                .union([
                                    zod
                                        .enum(['contains', 'regex', 'exact'])
                                        .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                                    zod.literal(null),
                                ])
                                .nullish()
                                .describe(
                                    'How to match the href value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                                ),
                            url: zod.string().nullish().describe('Page URL to match.'),
                            url_matching: zod
                                .union([
                                    zod
                                        .enum(['contains', 'regex', 'exact'])
                                        .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                                    zod.literal(null),
                                ])
                                .nullish()
                                .describe(
                                    'How to match the URL value. Defaults to contains.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                                ),
                        })
                    )
                    .optional()
                    .describe(
                        'Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.'
                    ),
                created_at: zod.string().datetime({}),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.string(),
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
                pinned_at: zod
                    .string()
                    .datetime({})
                    .nullish()
                    .describe(
                        'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
                    ),
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

export const actionsCreateBodyStepsItemPropertiesItemOperatorDefault = `exact`
export const actionsCreateBodyStepsItemPropertiesItemTypeDefault = `event`

export const ActionsCreateBody = zod
    .object({
        name: zod
            .string()
            .max(actionsCreateBodyNameMax)
            .nullish()
            .describe('Name of the action (must be unique within the project).'),
        description: zod.string().optional().describe('Human-readable description of what this action represents.'),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod
            .boolean()
            .optional()
            .describe('Whether to post a notification to Slack when this action is triggered.'),
        slack_message_format: zod
            .string()
            .max(actionsCreateBodySlackMessageFormatMax)
            .optional()
            .describe('Custom Slack message format. Supports templates with event properties.'),
        steps: zod
            .array(
                zod.object({
                    event: zod
                        .string()
                        .nullish()
                        .describe("Event name to match (e.g. '$pageview', '$autocapture', or a custom event name)."),
                    properties: zod
                        .array(
                            zod.object({
                                key: zod
                                    .string()
                                    .describe(
                                        "Key of the property you're filtering on. For example `email` or `$current_url`"
                                    ),
                                value: zod
                                    .union([
                                        zod.string(),
                                        zod.number(),
                                        zod.boolean(),
                                        zod.array(zod.union([zod.string(), zod.number()])),
                                    ])
                                    .describe(
                                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`'
                                    ),
                                operator: zod
                                    .union([
                                        zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'lt',
                                                'gte',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_after',
                                                'is_date_before',
                                                'in',
                                                'not_in',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                        zod.enum(['']),
                                        zod.literal(null),
                                    ])
                                    .default(actionsCreateBodyStepsItemPropertiesItemOperatorDefault),
                                type: zod
                                    .union([
                                        zod
                                            .enum([
                                                'event',
                                                'event_metadata',
                                                'feature',
                                                'person',
                                                'cohort',
                                                'element',
                                                'static-cohort',
                                                'dynamic-cohort',
                                                'precalculated-cohort',
                                                'group',
                                                'recording',
                                                'log_entry',
                                                'behavioral',
                                                'session',
                                                'hogql',
                                                'data_warehouse',
                                                'data_warehouse_person_property',
                                                'error_tracking_issue',
                                                'log',
                                                'log_attribute',
                                                'log_resource_attribute',
                                                'revenue_analytics',
                                                'flag',
                                                'workflow_variable',
                                            ])
                                            .describe(
                                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        zod.enum(['']),
                                    ])
                                    .default(actionsCreateBodyStepsItemPropertiesItemTypeDefault),
                            })
                        )
                        .nullish()
                        .describe(
                            "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
                        ),
                    selector: zod
                        .string()
                        .nullish()
                        .describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish().describe('HTML tag name to match (e.g. "button", "a", "input").'),
                    text: zod.string().nullish().describe('Element text content to match.'),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the text value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    href: zod.string().nullish().describe('Link href attribute to match.'),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the href value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    url: zod.string().nullish().describe('Page URL to match.'),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the URL value. Defaults to contains.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                })
            )
            .optional()
            .describe(
                'Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.'
            ),
        deleted: zod.boolean().optional(),
        last_calculated_at: zod.string().datetime({}).optional(),
        pinned_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
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

export const actionsRetrieveResponseStepsItemPropertiesItemOperatorDefault = `exact`
export const actionsRetrieveResponseStepsItemPropertiesItemTypeDefault = `event`
export const actionsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const actionsRetrieveResponseCreatedByOneFirstNameMax = 150

export const actionsRetrieveResponseCreatedByOneLastNameMax = 150

export const actionsRetrieveResponseCreatedByOneEmailMax = 254

export const actionsRetrieveResponseIsActionDefault = true

export const ActionsRetrieveResponse = zod
    .object({
        id: zod.number(),
        name: zod
            .string()
            .max(actionsRetrieveResponseNameMax)
            .nullish()
            .describe('Name of the action (must be unique within the project).'),
        description: zod.string().optional().describe('Human-readable description of what this action represents.'),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod
            .boolean()
            .optional()
            .describe('Whether to post a notification to Slack when this action is triggered.'),
        slack_message_format: zod
            .string()
            .max(actionsRetrieveResponseSlackMessageFormatMax)
            .optional()
            .describe('Custom Slack message format. Supports templates with event properties.'),
        steps: zod
            .array(
                zod.object({
                    event: zod
                        .string()
                        .nullish()
                        .describe("Event name to match (e.g. '$pageview', '$autocapture', or a custom event name)."),
                    properties: zod
                        .array(
                            zod.object({
                                key: zod
                                    .string()
                                    .describe(
                                        "Key of the property you're filtering on. For example `email` or `$current_url`"
                                    ),
                                value: zod
                                    .union([
                                        zod.string(),
                                        zod.number(),
                                        zod.boolean(),
                                        zod.array(zod.union([zod.string(), zod.number()])),
                                    ])
                                    .describe(
                                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`'
                                    ),
                                operator: zod
                                    .union([
                                        zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'lt',
                                                'gte',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_after',
                                                'is_date_before',
                                                'in',
                                                'not_in',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                        zod.enum(['']),
                                        zod.literal(null),
                                    ])
                                    .default(actionsRetrieveResponseStepsItemPropertiesItemOperatorDefault),
                                type: zod
                                    .union([
                                        zod
                                            .enum([
                                                'event',
                                                'event_metadata',
                                                'feature',
                                                'person',
                                                'cohort',
                                                'element',
                                                'static-cohort',
                                                'dynamic-cohort',
                                                'precalculated-cohort',
                                                'group',
                                                'recording',
                                                'log_entry',
                                                'behavioral',
                                                'session',
                                                'hogql',
                                                'data_warehouse',
                                                'data_warehouse_person_property',
                                                'error_tracking_issue',
                                                'log',
                                                'log_attribute',
                                                'log_resource_attribute',
                                                'revenue_analytics',
                                                'flag',
                                                'workflow_variable',
                                            ])
                                            .describe(
                                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        zod.enum(['']),
                                    ])
                                    .default(actionsRetrieveResponseStepsItemPropertiesItemTypeDefault),
                            })
                        )
                        .nullish()
                        .describe(
                            "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
                        ),
                    selector: zod
                        .string()
                        .nullish()
                        .describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish().describe('HTML tag name to match (e.g. "button", "a", "input").'),
                    text: zod.string().nullish().describe('Element text content to match.'),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the text value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    href: zod.string().nullish().describe('Link href attribute to match.'),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the href value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    url: zod.string().nullish().describe('Page URL to match.'),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the URL value. Defaults to contains.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                })
            )
            .optional()
            .describe(
                'Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.'
            ),
        created_at: zod.string().datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.string(),
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
        pinned_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
        creation_context: zod.string(),
        _create_in_folder: zod.string().optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const ActionsUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsUpdateQueryParams = zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const actionsUpdateBodyNameMax = 400

export const actionsUpdateBodySlackMessageFormatMax = 1200

export const actionsUpdateBodyStepsItemPropertiesItemOperatorDefault = `exact`
export const actionsUpdateBodyStepsItemPropertiesItemTypeDefault = `event`

export const ActionsUpdateBody = zod
    .object({
        name: zod
            .string()
            .max(actionsUpdateBodyNameMax)
            .nullish()
            .describe('Name of the action (must be unique within the project).'),
        description: zod.string().optional().describe('Human-readable description of what this action represents.'),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod
            .boolean()
            .optional()
            .describe('Whether to post a notification to Slack when this action is triggered.'),
        slack_message_format: zod
            .string()
            .max(actionsUpdateBodySlackMessageFormatMax)
            .optional()
            .describe('Custom Slack message format. Supports templates with event properties.'),
        steps: zod
            .array(
                zod.object({
                    event: zod
                        .string()
                        .nullish()
                        .describe("Event name to match (e.g. '$pageview', '$autocapture', or a custom event name)."),
                    properties: zod
                        .array(
                            zod.object({
                                key: zod
                                    .string()
                                    .describe(
                                        "Key of the property you're filtering on. For example `email` or `$current_url`"
                                    ),
                                value: zod
                                    .union([
                                        zod.string(),
                                        zod.number(),
                                        zod.boolean(),
                                        zod.array(zod.union([zod.string(), zod.number()])),
                                    ])
                                    .describe(
                                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`'
                                    ),
                                operator: zod
                                    .union([
                                        zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'lt',
                                                'gte',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_after',
                                                'is_date_before',
                                                'in',
                                                'not_in',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                        zod.enum(['']),
                                        zod.literal(null),
                                    ])
                                    .default(actionsUpdateBodyStepsItemPropertiesItemOperatorDefault),
                                type: zod
                                    .union([
                                        zod
                                            .enum([
                                                'event',
                                                'event_metadata',
                                                'feature',
                                                'person',
                                                'cohort',
                                                'element',
                                                'static-cohort',
                                                'dynamic-cohort',
                                                'precalculated-cohort',
                                                'group',
                                                'recording',
                                                'log_entry',
                                                'behavioral',
                                                'session',
                                                'hogql',
                                                'data_warehouse',
                                                'data_warehouse_person_property',
                                                'error_tracking_issue',
                                                'log',
                                                'log_attribute',
                                                'log_resource_attribute',
                                                'revenue_analytics',
                                                'flag',
                                                'workflow_variable',
                                            ])
                                            .describe(
                                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        zod.enum(['']),
                                    ])
                                    .default(actionsUpdateBodyStepsItemPropertiesItemTypeDefault),
                            })
                        )
                        .nullish()
                        .describe(
                            "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
                        ),
                    selector: zod
                        .string()
                        .nullish()
                        .describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish().describe('HTML tag name to match (e.g. "button", "a", "input").'),
                    text: zod.string().nullish().describe('Element text content to match.'),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the text value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    href: zod.string().nullish().describe('Link href attribute to match.'),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the href value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    url: zod.string().nullish().describe('Page URL to match.'),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the URL value. Defaults to contains.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                })
            )
            .optional()
            .describe(
                'Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.'
            ),
        deleted: zod.boolean().optional(),
        last_calculated_at: zod.string().datetime({}).optional(),
        pinned_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const actionsUpdateResponseNameMax = 400

export const actionsUpdateResponseSlackMessageFormatMax = 1200

export const actionsUpdateResponseStepsItemPropertiesItemOperatorDefault = `exact`
export const actionsUpdateResponseStepsItemPropertiesItemTypeDefault = `event`
export const actionsUpdateResponseCreatedByOneDistinctIdMax = 200

export const actionsUpdateResponseCreatedByOneFirstNameMax = 150

export const actionsUpdateResponseCreatedByOneLastNameMax = 150

export const actionsUpdateResponseCreatedByOneEmailMax = 254

export const actionsUpdateResponseIsActionDefault = true

export const ActionsUpdateResponse = zod
    .object({
        id: zod.number(),
        name: zod
            .string()
            .max(actionsUpdateResponseNameMax)
            .nullish()
            .describe('Name of the action (must be unique within the project).'),
        description: zod.string().optional().describe('Human-readable description of what this action represents.'),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod
            .boolean()
            .optional()
            .describe('Whether to post a notification to Slack when this action is triggered.'),
        slack_message_format: zod
            .string()
            .max(actionsUpdateResponseSlackMessageFormatMax)
            .optional()
            .describe('Custom Slack message format. Supports templates with event properties.'),
        steps: zod
            .array(
                zod.object({
                    event: zod
                        .string()
                        .nullish()
                        .describe("Event name to match (e.g. '$pageview', '$autocapture', or a custom event name)."),
                    properties: zod
                        .array(
                            zod.object({
                                key: zod
                                    .string()
                                    .describe(
                                        "Key of the property you're filtering on. For example `email` or `$current_url`"
                                    ),
                                value: zod
                                    .union([
                                        zod.string(),
                                        zod.number(),
                                        zod.boolean(),
                                        zod.array(zod.union([zod.string(), zod.number()])),
                                    ])
                                    .describe(
                                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`'
                                    ),
                                operator: zod
                                    .union([
                                        zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'lt',
                                                'gte',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_after',
                                                'is_date_before',
                                                'in',
                                                'not_in',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                        zod.enum(['']),
                                        zod.literal(null),
                                    ])
                                    .default(actionsUpdateResponseStepsItemPropertiesItemOperatorDefault),
                                type: zod
                                    .union([
                                        zod
                                            .enum([
                                                'event',
                                                'event_metadata',
                                                'feature',
                                                'person',
                                                'cohort',
                                                'element',
                                                'static-cohort',
                                                'dynamic-cohort',
                                                'precalculated-cohort',
                                                'group',
                                                'recording',
                                                'log_entry',
                                                'behavioral',
                                                'session',
                                                'hogql',
                                                'data_warehouse',
                                                'data_warehouse_person_property',
                                                'error_tracking_issue',
                                                'log',
                                                'log_attribute',
                                                'log_resource_attribute',
                                                'revenue_analytics',
                                                'flag',
                                                'workflow_variable',
                                            ])
                                            .describe(
                                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        zod.enum(['']),
                                    ])
                                    .default(actionsUpdateResponseStepsItemPropertiesItemTypeDefault),
                            })
                        )
                        .nullish()
                        .describe(
                            "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
                        ),
                    selector: zod
                        .string()
                        .nullish()
                        .describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish().describe('HTML tag name to match (e.g. "button", "a", "input").'),
                    text: zod.string().nullish().describe('Element text content to match.'),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the text value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    href: zod.string().nullish().describe('Link href attribute to match.'),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the href value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    url: zod.string().nullish().describe('Page URL to match.'),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the URL value. Defaults to contains.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                })
            )
            .optional()
            .describe(
                'Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.'
            ),
        created_at: zod.string().datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.string(),
            distinct_id: zod.string().max(actionsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(actionsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(actionsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(actionsUpdateResponseCreatedByOneEmailMax),
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
        pinned_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
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

export const actionsPartialUpdateBodyStepsItemPropertiesItemOperatorDefault = `exact`
export const actionsPartialUpdateBodyStepsItemPropertiesItemTypeDefault = `event`

export const ActionsPartialUpdateBody = zod
    .object({
        name: zod
            .string()
            .max(actionsPartialUpdateBodyNameMax)
            .nullish()
            .describe('Name of the action (must be unique within the project).'),
        description: zod.string().optional().describe('Human-readable description of what this action represents.'),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod
            .boolean()
            .optional()
            .describe('Whether to post a notification to Slack when this action is triggered.'),
        slack_message_format: zod
            .string()
            .max(actionsPartialUpdateBodySlackMessageFormatMax)
            .optional()
            .describe('Custom Slack message format. Supports templates with event properties.'),
        steps: zod
            .array(
                zod.object({
                    event: zod
                        .string()
                        .nullish()
                        .describe("Event name to match (e.g. '$pageview', '$autocapture', or a custom event name)."),
                    properties: zod
                        .array(
                            zod.object({
                                key: zod
                                    .string()
                                    .describe(
                                        "Key of the property you're filtering on. For example `email` or `$current_url`"
                                    ),
                                value: zod
                                    .union([
                                        zod.string(),
                                        zod.number(),
                                        zod.boolean(),
                                        zod.array(zod.union([zod.string(), zod.number()])),
                                    ])
                                    .describe(
                                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`'
                                    ),
                                operator: zod
                                    .union([
                                        zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'lt',
                                                'gte',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_after',
                                                'is_date_before',
                                                'in',
                                                'not_in',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                        zod.enum(['']),
                                        zod.literal(null),
                                    ])
                                    .default(actionsPartialUpdateBodyStepsItemPropertiesItemOperatorDefault),
                                type: zod
                                    .union([
                                        zod
                                            .enum([
                                                'event',
                                                'event_metadata',
                                                'feature',
                                                'person',
                                                'cohort',
                                                'element',
                                                'static-cohort',
                                                'dynamic-cohort',
                                                'precalculated-cohort',
                                                'group',
                                                'recording',
                                                'log_entry',
                                                'behavioral',
                                                'session',
                                                'hogql',
                                                'data_warehouse',
                                                'data_warehouse_person_property',
                                                'error_tracking_issue',
                                                'log',
                                                'log_attribute',
                                                'log_resource_attribute',
                                                'revenue_analytics',
                                                'flag',
                                                'workflow_variable',
                                            ])
                                            .describe(
                                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        zod.enum(['']),
                                    ])
                                    .default(actionsPartialUpdateBodyStepsItemPropertiesItemTypeDefault),
                            })
                        )
                        .nullish()
                        .describe(
                            "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
                        ),
                    selector: zod
                        .string()
                        .nullish()
                        .describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish().describe('HTML tag name to match (e.g. "button", "a", "input").'),
                    text: zod.string().nullish().describe('Element text content to match.'),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the text value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    href: zod.string().nullish().describe('Link href attribute to match.'),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the href value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    url: zod.string().nullish().describe('Page URL to match.'),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the URL value. Defaults to contains.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                })
            )
            .optional()
            .describe(
                'Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.'
            ),
        deleted: zod.boolean().optional(),
        last_calculated_at: zod.string().datetime({}).optional(),
        pinned_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const actionsPartialUpdateResponseNameMax = 400

export const actionsPartialUpdateResponseSlackMessageFormatMax = 1200

export const actionsPartialUpdateResponseStepsItemPropertiesItemOperatorDefault = `exact`
export const actionsPartialUpdateResponseStepsItemPropertiesItemTypeDefault = `event`
export const actionsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const actionsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const actionsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const actionsPartialUpdateResponseCreatedByOneEmailMax = 254

export const actionsPartialUpdateResponseIsActionDefault = true

export const ActionsPartialUpdateResponse = zod
    .object({
        id: zod.number(),
        name: zod
            .string()
            .max(actionsPartialUpdateResponseNameMax)
            .nullish()
            .describe('Name of the action (must be unique within the project).'),
        description: zod.string().optional().describe('Human-readable description of what this action represents.'),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod
            .boolean()
            .optional()
            .describe('Whether to post a notification to Slack when this action is triggered.'),
        slack_message_format: zod
            .string()
            .max(actionsPartialUpdateResponseSlackMessageFormatMax)
            .optional()
            .describe('Custom Slack message format. Supports templates with event properties.'),
        steps: zod
            .array(
                zod.object({
                    event: zod
                        .string()
                        .nullish()
                        .describe("Event name to match (e.g. '$pageview', '$autocapture', or a custom event name)."),
                    properties: zod
                        .array(
                            zod.object({
                                key: zod
                                    .string()
                                    .describe(
                                        "Key of the property you're filtering on. For example `email` or `$current_url`"
                                    ),
                                value: zod
                                    .union([
                                        zod.string(),
                                        zod.number(),
                                        zod.boolean(),
                                        zod.array(zod.union([zod.string(), zod.number()])),
                                    ])
                                    .describe(
                                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`'
                                    ),
                                operator: zod
                                    .union([
                                        zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'lt',
                                                'gte',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_after',
                                                'is_date_before',
                                                'in',
                                                'not_in',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                        zod.enum(['']),
                                        zod.literal(null),
                                    ])
                                    .default(actionsPartialUpdateResponseStepsItemPropertiesItemOperatorDefault),
                                type: zod
                                    .union([
                                        zod
                                            .enum([
                                                'event',
                                                'event_metadata',
                                                'feature',
                                                'person',
                                                'cohort',
                                                'element',
                                                'static-cohort',
                                                'dynamic-cohort',
                                                'precalculated-cohort',
                                                'group',
                                                'recording',
                                                'log_entry',
                                                'behavioral',
                                                'session',
                                                'hogql',
                                                'data_warehouse',
                                                'data_warehouse_person_property',
                                                'error_tracking_issue',
                                                'log',
                                                'log_attribute',
                                                'log_resource_attribute',
                                                'revenue_analytics',
                                                'flag',
                                                'workflow_variable',
                                            ])
                                            .describe(
                                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        zod.enum(['']),
                                    ])
                                    .default(actionsPartialUpdateResponseStepsItemPropertiesItemTypeDefault),
                            })
                        )
                        .nullish()
                        .describe(
                            "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
                        ),
                    selector: zod
                        .string()
                        .nullish()
                        .describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
                    selector_regex: zod.string().nullable(),
                    tag_name: zod.string().nullish().describe('HTML tag name to match (e.g. "button", "a", "input").'),
                    text: zod.string().nullish().describe('Element text content to match.'),
                    text_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the text value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    href: zod.string().nullish().describe('Link href attribute to match.'),
                    href_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the href value. Defaults to exact.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                    url: zod.string().nullish().describe('Page URL to match.'),
                    url_matching: zod
                        .union([
                            zod
                                .enum(['contains', 'regex', 'exact'])
                                .describe('* `contains` - contains\n* `regex` - regex\n* `exact` - exact'),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'How to match the URL value. Defaults to contains.\n\n* `contains` - contains\n* `regex` - regex\n* `exact` - exact'
                        ),
                })
            )
            .optional()
            .describe(
                'Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.'
            ),
        created_at: zod.string().datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.string(),
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
        pinned_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
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
