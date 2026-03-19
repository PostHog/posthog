/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ActionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsListQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ActionsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const actionsCreateBodyNameMax = 400

export const actionsCreateBodySlackMessageFormatMax = 1200

export const actionsCreateBodyStepsItemPropertiesItemOneTypeDefault = `event`
export const actionsCreateBodyStepsItemPropertiesItemOneOperatorDefault = `exact`
export const actionsCreateBodyStepsItemPropertiesItemTwoTypeDefault = `event`
export const actionsCreateBodyStepsItemPropertiesItemTwoOperatorDefault = `exact`
export const actionsCreateBodyStepsItemPropertiesItemThreeTypeDefault = `event`
export const actionsCreateBodyStepsItemPropertiesItemThreeOperatorDefault = `exact`
export const actionsCreateBodyStepsItemPropertiesItemFourTypeDefault = `event`
export const actionsCreateBodyStepsItemPropertiesItemFourOperatorDefault = `is_date_exact`
export const actionsCreateBodyStepsItemPropertiesItemFiveTypeDefault = `event`

export const ActionsCreateBody = /* @__PURE__ */ zod
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
                            zod.union([
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsCreateBodyStepsItemPropertiesItemOneTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        value: zod.string().describe('String value to match against.'),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex'
                                            )
                                            .default(actionsCreateBodyStepsItemPropertiesItemOneOperatorDefault)
                                            .describe(
                                                'String comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex'
                                            ),
                                    })
                                    .describe('Matches string values with text-oriented operators.'),
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsCreateBodyStepsItemPropertiesItemTwoTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        value: zod.number().describe('Numeric value to compare against.'),
                                        operator: zod
                                            .enum(['exact', 'is_not', 'gt', 'lt', 'gte', 'lte'])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte'
                                            )
                                            .default(actionsCreateBodyStepsItemPropertiesItemTwoOperatorDefault)
                                            .describe(
                                                'Numeric comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte'
                                            ),
                                    })
                                    .describe('Matches numeric values with comparison operators.'),
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsCreateBodyStepsItemPropertiesItemThreeTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        value: zod
                                            .array(zod.string())
                                            .describe(
                                                'List of values to match. For example `["test@example.com", "ok@example.com"]`.'
                                            ),
                                        operator: zod
                                            .enum(['exact', 'is_not', 'in', 'not_in'])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `in` - in\n* `not_in` - not_in'
                                            )
                                            .default(actionsCreateBodyStepsItemPropertiesItemThreeOperatorDefault)
                                            .describe(
                                                'Array comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                    })
                                    .describe(
                                        'Matches against a list of values (OR semantics for exact/is_not, set membership for in/not_in).'
                                    ),
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsCreateBodyStepsItemPropertiesItemFourTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        value: zod
                                            .string()
                                            .describe(
                                                "Date or datetime string in ISO 8601 format (e.g. '2024-01-15' or '2024-01-15T10:30:00Z')."
                                            ),
                                        operator: zod
                                            .enum(['is_date_exact', 'is_date_before', 'is_date_after'])
                                            .describe(
                                                '* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after'
                                            )
                                            .default(actionsCreateBodyStepsItemPropertiesItemFourOperatorDefault)
                                            .describe(
                                                'Date comparison operator.\n\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after'
                                            ),
                                    })
                                    .describe('Matches date/datetime values with date-specific operators.'),
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsCreateBodyStepsItemPropertiesItemFiveTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        operator: zod
                                            .enum(['is_set', 'is_not_set'])
                                            .describe('* `is_set` - is_set\n* `is_not_set` - is_not_set')
                                            .describe(
                                                'Existence check operator.\n\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                                            ),
                                    })
                                    .describe('Checks whether a property is set or not, without comparing values.'),
                            ])
                        )
                        .nullish()
                        .describe(
                            "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
                        ),
                    selector: zod
                        .string()
                        .nullish()
                        .describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
                    selector_regex: zod.string().nullish(),
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
        pinned_at: zod.iso
            .datetime({})
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const ActionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const ActionsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsPartialUpdateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const actionsPartialUpdateBodyNameMax = 400

export const actionsPartialUpdateBodySlackMessageFormatMax = 1200

export const actionsPartialUpdateBodyStepsItemPropertiesItemOneTypeDefault = `event`
export const actionsPartialUpdateBodyStepsItemPropertiesItemOneOperatorDefault = `exact`
export const actionsPartialUpdateBodyStepsItemPropertiesItemTwoTypeDefault = `event`
export const actionsPartialUpdateBodyStepsItemPropertiesItemTwoOperatorDefault = `exact`
export const actionsPartialUpdateBodyStepsItemPropertiesItemThreeTypeDefault = `event`
export const actionsPartialUpdateBodyStepsItemPropertiesItemThreeOperatorDefault = `exact`
export const actionsPartialUpdateBodyStepsItemPropertiesItemFourTypeDefault = `event`
export const actionsPartialUpdateBodyStepsItemPropertiesItemFourOperatorDefault = `is_date_exact`
export const actionsPartialUpdateBodyStepsItemPropertiesItemFiveTypeDefault = `event`

export const ActionsPartialUpdateBody = /* @__PURE__ */ zod
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
                            zod.union([
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsPartialUpdateBodyStepsItemPropertiesItemOneTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        value: zod.string().describe('String value to match against.'),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex'
                                            )
                                            .default(actionsPartialUpdateBodyStepsItemPropertiesItemOneOperatorDefault)
                                            .describe(
                                                'String comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex'
                                            ),
                                    })
                                    .describe('Matches string values with text-oriented operators.'),
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsPartialUpdateBodyStepsItemPropertiesItemTwoTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        value: zod.number().describe('Numeric value to compare against.'),
                                        operator: zod
                                            .enum(['exact', 'is_not', 'gt', 'lt', 'gte', 'lte'])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte'
                                            )
                                            .default(actionsPartialUpdateBodyStepsItemPropertiesItemTwoOperatorDefault)
                                            .describe(
                                                'Numeric comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte'
                                            ),
                                    })
                                    .describe('Matches numeric values with comparison operators.'),
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsPartialUpdateBodyStepsItemPropertiesItemThreeTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        value: zod
                                            .array(zod.string())
                                            .describe(
                                                'List of values to match. For example `["test@example.com", "ok@example.com"]`.'
                                            ),
                                        operator: zod
                                            .enum(['exact', 'is_not', 'in', 'not_in'])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `in` - in\n* `not_in` - not_in'
                                            )
                                            .default(
                                                actionsPartialUpdateBodyStepsItemPropertiesItemThreeOperatorDefault
                                            )
                                            .describe(
                                                'Array comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                    })
                                    .describe(
                                        'Matches against a list of values (OR semantics for exact/is_not, set membership for in/not_in).'
                                    ),
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsPartialUpdateBodyStepsItemPropertiesItemFourTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        value: zod
                                            .string()
                                            .describe(
                                                "Date or datetime string in ISO 8601 format (e.g. '2024-01-15' or '2024-01-15T10:30:00Z')."
                                            ),
                                        operator: zod
                                            .enum(['is_date_exact', 'is_date_before', 'is_date_after'])
                                            .describe(
                                                '* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after'
                                            )
                                            .default(actionsPartialUpdateBodyStepsItemPropertiesItemFourOperatorDefault)
                                            .describe(
                                                'Date comparison operator.\n\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after'
                                            ),
                                    })
                                    .describe('Matches date/datetime values with date-specific operators.'),
                                zod
                                    .object({
                                        key: zod
                                            .string()
                                            .describe(
                                                "Key of the property you're filtering on. For example `email` or `$current_url`."
                                            ),
                                        type: zod
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
                                            )
                                            .default(actionsPartialUpdateBodyStepsItemPropertiesItemFiveTypeDefault)
                                            .describe(
                                                'Property type (event, person, session, etc.).\n\n* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                                            ),
                                        operator: zod
                                            .enum(['is_set', 'is_not_set'])
                                            .describe('* `is_set` - is_set\n* `is_not_set` - is_not_set')
                                            .describe(
                                                'Existence check operator.\n\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                                            ),
                                    })
                                    .describe('Checks whether a property is set or not, without comparing values.'),
                            ])
                        )
                        .nullish()
                        .describe(
                            "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
                        ),
                    selector: zod
                        .string()
                        .nullish()
                        .describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
                    selector_regex: zod.string().nullish(),
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
        pinned_at: zod.iso
            .datetime({})
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const ActionsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActionsDestroyQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})
