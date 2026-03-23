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
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const personsListQueryPropertiesItemTypeDefault = `AND`
export const personsListQueryPropertiesItemValuesItemOperatorDefault = `exact`
export const personsListQueryPropertiesItemValuesItemTypeDefault = `event`

export const PersonsListQueryParams = /* @__PURE__ */ zod.object({
    distinct_id: zod.string().optional().describe('Filter list by distinct id.'),
    email: zod.string().optional().describe('Filter persons by email (exact match)'),
    format: zod.enum(['csv', 'json']).optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    properties: zod
        .array(
            zod.object({
                type: zod
                    .enum(['AND', 'OR'])
                    .default(personsListQueryPropertiesItemTypeDefault)
                    .describe(
                        '\n You can use a simplified version:\n```json\n{\n    "properties": [\n        {\n            "key": "email",\n            "value": "x@y.com",\n            "operator": "exact",\n            "type": "event"\n        }\n    ]\n}\n```\n\nOr you can create more complicated queries with AND and OR:\n```json\n{\n    "properties": {\n        "type": "AND",\n        "values": [\n            {\n                "type": "OR",\n                "values": [\n                    {"key": "email", ...},\n                    {"key": "email", ...}\n                ]\n            },\n            {\n                "type": "AND",\n                "values": [\n                    {"key": "email", ...},\n                    {"key": "email", ...}\n                ]\n            }\n        ]\n    ]\n}\n```\n\n\n* `AND` - AND\n* `OR` - OR'
                    ),
                values: zod.array(
                    zod.object({
                        key: zod
                            .string()
                            .describe("Key of the property you're filtering on. For example `email` or `$current_url`"),
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
                            .default(personsListQueryPropertiesItemValuesItemOperatorDefault),
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
                            .default(personsListQueryPropertiesItemValuesItemTypeDefault),
                    })
                ),
            })
        )
        .optional()
        .describe('Filter Persons by person properties.'),
    search: zod
        .string()
        .optional()
        .describe('Search persons, either by email (full text search) or distinct_id (exact match).'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A unique value identifying this person. Accepts both numeric ID and UUID.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PersonsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsDeletePropertyCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A unique value identifying this person. Accepts both numeric ID and UUID.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PersonsDeletePropertyCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const PersonsDeletePropertyCreateBody = /* @__PURE__ */ zod.object({
    $unset: zod.string().describe('The property key to remove from this person.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsUpdatePropertyCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A unique value identifying this person. Accepts both numeric ID and UUID.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PersonsUpdatePropertyCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const PersonsUpdatePropertyCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().describe('The property key to set.'),
    value: zod.unknown().describe('The property value. Can be a string, number, boolean, or object.'),
})

/**
 * This endpoint allows you to bulk delete persons, either by the PostHog person IDs or by distinct IDs. You can pass in a maximum of 1000 IDs per call. Only events captured before the request will be deleted.
 */
export const PersonsBulkDeleteCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PersonsBulkDeleteCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const personsBulkDeleteCreateBodyDeleteEventsDefault = false
export const personsBulkDeleteCreateBodyDeleteRecordingsDefault = false
export const personsBulkDeleteCreateBodyKeepPersonDefault = false

export const PersonsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.string()).optional().describe('A list of PostHog person UUIDs to delete (max 1000).'),
    distinct_ids: zod
        .array(zod.string())
        .optional()
        .describe('A list of distinct IDs whose associated persons will be deleted (max 1000).'),
    delete_events: zod
        .boolean()
        .default(personsBulkDeleteCreateBodyDeleteEventsDefault)
        .describe('If true, queue deletion of all events associated with these persons.'),
    delete_recordings: zod
        .boolean()
        .default(personsBulkDeleteCreateBodyDeleteRecordingsDefault)
        .describe('If true, queue deletion of all recordings associated with these persons.'),
    keep_person: zod
        .boolean()
        .default(personsBulkDeleteCreateBodyKeepPersonDefault)
        .describe('If true, keep the person records but delete their events and recordings.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsCohortsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PersonsCohortsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
    person_id: zod.string().describe('The person ID or UUID to get cohorts for.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsValuesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PersonsValuesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['csv', 'json']).optional(),
    key: zod.string().describe("The person property key to get values for (e.g., 'email', 'plan', 'role')."),
    value: zod
        .string()
        .optional()
        .describe('Optional search string to filter values (case-insensitive substring match).'),
})
