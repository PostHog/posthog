/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const PropertyGroupOperatorApi = zod.enum(['AND', 'OR'])

export type PropertyGroupOperatorApi = zod.input<typeof PropertyGroupOperatorApi>
export type PropertyGroupOperatorApiOutput = zod.output<typeof PropertyGroupOperatorApi>

export const PropertyItemOperatorEnumApi = zod
    .enum([
        'exact',
        'is_not',
        'icontains',
        'not_icontains',
        'starts_with',
        'not_starts_with',
        'ends_with',
        'not_ends_with',
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
        '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `gte` - gte\n\* `lte` - lte\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set\n\* `is_date_exact` - is_date_exact\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before\n\* `in` - in\n\* `not_in` - not_in'
    )

export type PropertyItemOperatorEnumApi = zod.input<typeof PropertyItemOperatorEnumApi>
export type PropertyItemOperatorEnumApiOutput = zod.output<typeof PropertyItemOperatorEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const PropertyFilterTypeEnumApi = zod
    .enum([
        'event',
        'event_metadata',
        'feature',
        'person',
        'person_metadata',
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
        'metric_attribute',
        'span',
        'span_attribute',
        'span_resource_attribute',
        'revenue_analytics',
        'account_custom_property',
        'flag',
        'workflow_variable',
    ])
    .describe(
        '\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `account_custom_property` - account_custom_property\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
    )

export type PropertyFilterTypeEnumApi = zod.input<typeof PropertyFilterTypeEnumApi>
export type PropertyFilterTypeEnumApiOutput = zod.output<typeof PropertyFilterTypeEnumApi>

export const propertyItemApiOperatorDefault = `exact`
export const propertyItemApiTypeDefault = `event`

export const PropertyItemApi = zod.object({
    key: zod.string().describe("Key of the property you're filtering on. For example `email` or `$current_url`"),
    value: zod
        .union([zod.string(), zod.number(), zod.boolean(), zod.array(zod.union([zod.string(), zod.number()]))])
        .describe(
            'Value of your filter. For example `test@example.com` or `https:\/\/example.com\/test\/`. Can be an array for an OR query, like `[\"test@example.com\",\"ok@example.com\"]`'
        ),
    operator: zod
        .union([PropertyItemOperatorEnumApi, BlankEnumApi, zod.null()])
        .default(propertyItemApiOperatorDefault),
    type: zod.union([PropertyFilterTypeEnumApi, BlankEnumApi]).default(propertyItemApiTypeDefault),
})

export type PropertyItemApi = zod.input<typeof PropertyItemApi>
export type PropertyItemApiOutput = zod.output<typeof PropertyItemApi>

export const propertyApiTypeDefault = `AND`

export const PropertyApi = zod.object({
    type: PropertyGroupOperatorApi.default(propertyApiTypeDefault).describe(
        '\n You can use a simplified version:\n```json\n{\n    \"properties\": [\n        {\n            \"key\": \"email\",\n            \"value\": \"x@y.com\",\n            \"operator\": \"exact\",\n            \"type\": \"event\"\n        }\n    ]\n}\n```\n\nOr you can create more complicated queries with AND and OR:\n```json\n{\n    \"properties\": {\n        \"type\": \"AND\",\n        \"values\": [\n            {\n                \"type\": \"OR\",\n                \"values\": [\n                    {\"key\": \"email\", ...},\n                    {\"key\": \"email\", ...}\n                ]\n            },\n            {\n                \"type\": \"AND\",\n                \"values\": [\n                    {\"key\": \"email\", ...},\n                    {\"key\": \"email\", ...}\n                ]\n            }\n        ]\n    ]\n}\n```\n\n\n\* `AND` - AND\n\* `OR` - OR'
    ),
    values: zod.array(PropertyItemApi),
})

export type PropertyApi = zod.input<typeof PropertyApi>
export type PropertyApiOutput = zod.output<typeof PropertyApi>

export const PersonRecordApi = zod.object({
    id: zod.number().describe('Numeric person ID.'),
    name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
    distinct_ids: zod.array(zod.string()),
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When this person was first seen (ISO 8601).'),
    uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
    last_seen_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp of the last event from this person, or null.'),
})

export type PersonRecordApi = zod.input<typeof PersonRecordApi>
export type PersonRecordApiOutput = zod.output<typeof PersonRecordApi>

export const PaginatedPersonRecordListApi = zod.object({
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    count: zod.number().optional(),
    results: zod.array(PersonRecordApi).optional(),
})

export type PaginatedPersonRecordListApi = zod.input<typeof PaginatedPersonRecordListApi>
export type PaginatedPersonRecordListApiOutput = zod.output<typeof PaginatedPersonRecordListApi>

export const PatchedPersonRecordApi = zod.object({
    id: zod.number().optional().describe('Numeric person ID.'),
    name: zod.string().optional().describe('Display name derived from person properties (email, name, or username).'),
    distinct_ids: zod.array(zod.string()).optional(),
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
    created_at: zod.iso.datetime({ offset: true }).optional().describe('When this person was first seen (ISO 8601).'),
    uuid: zod.uuid().optional().describe('Unique identifier (UUID) for this person.'),
    last_seen_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Timestamp of the last event from this person, or null.'),
})

export type PatchedPersonRecordApi = zod.input<typeof PatchedPersonRecordApi>
export type PatchedPersonRecordApiOutput = zod.output<typeof PatchedPersonRecordApi>

export const personDeletePropertyRequestApiUnsetTwoMax = 1000

export const PersonDeletePropertyRequestApi = zod.object({
    $unset: zod
        .union([
            zod.string().min(1),
            zod.array(zod.string().min(1)).min(1).max(personDeletePropertyRequestApiUnsetTwoMax),
        ])
        .describe('A property key, or a list of property keys, to remove from this person.'),
})

export type PersonDeletePropertyRequestApi = zod.input<typeof PersonDeletePropertyRequestApi>
export type PersonDeletePropertyRequestApiOutput = zod.output<typeof PersonDeletePropertyRequestApi>

export const MessageAssetApi = zod.object({
    invocation_id: zod.string().describe('The workflow run this email was sent in.'),
    action_id: zod.string().describe('The email step (action node) within the workflow that sent this email.'),
    function_id: zod
        .string()
        .describe(
            "The workflow id that sent this email — used to navigate from a person's Emails tab back into the originating workflow."
        ),
    function_name: zod
        .string()
        .describe(
            'Human-readable workflow name for display. Empty when the workflow has been deleted; clients should fall back to function_id in that case.'
        ),
    parent_run_id: zod
        .string()
        .describe(
            'The batch run this email belongs to, for batch-triggered workflows. Empty for event-triggered runs.'
        ),
    kind: zod
        .string()
        .describe(
            "Message channel this asset was sent on: 'email' or 'push'. The per-person endpoints return one channel each."
        ),
    distinct_id: zod.string().describe("The recipient's distinct_id."),
    person_id: zod.string().describe("The recipient's person UUID, if resolved."),
    recipient: zod
        .string()
        .describe("Who the message went to: the email address for 'email', or the recipient's distinct ID for 'push'."),
    subject: zod.string().describe('The email subject line, or the push notification title.'),
    status: zod
        .string()
        .describe("Delivery status at capture time. Currently always 'sent' - only delivered messages are captured."),
    sent_at: zod.iso.datetime({ offset: true }).describe('When the message was sent.'),
})

export type MessageAssetApi = zod.input<typeof MessageAssetApi>
export type MessageAssetApiOutput = zod.output<typeof MessageAssetApi>

export const PersonSplitRequestApi = zod.object({
    main_distinct_id: zod
        .string()
        .nullish()
        .describe(
            'The distinct_id to \*\*keep\*\* on this person; every \*other\* distinct_id is moved to its own new single-id person. If omitted, the first distinct_id on the person is kept. The original person always retains its properties; to clear individual properties afterward, use the delete_property endpoint. To surgically \*remove\* one or more distinct_ids while leaving the merge intact, use `distinct_ids_to_split` instead — these parameters are inverses of each other and cannot be combined.'
        ),
    distinct_ids_to_split: zod
        .array(zod.string())
        .nullish()
        .describe(
            'List of distinct_ids to \*\*move off\*\* this person onto new single-id persons. The original person keeps every other distinct_id and its properties. New persons are created with deterministic UUIDs derived from `(team_id, distinct_id)`. Cannot be combined with `main_distinct_id`.'
        ),
})

export type PersonSplitRequestApi = zod.input<typeof PersonSplitRequestApi>
export type PersonSplitRequestApiOutput = zod.output<typeof PersonSplitRequestApi>

export const PersonSplitResponseApi = zod.object({
    success: zod
        .boolean()
        .describe(
            'Always `true` when the split task was enqueued. The split itself runs asynchronously — a 201 response means the task was accepted, not that the merge state has already been updated.'
        ),
})

export type PersonSplitResponseApi = zod.input<typeof PersonSplitResponseApi>
export type PersonSplitResponseApiOutput = zod.output<typeof PersonSplitResponseApi>

export const PersonUpdatePropertyRequestApi = zod.object({
    key: zod.string().describe('The property key to set.'),
    value: zod.unknown().describe('The property value. Can be a string, number, boolean, or object.'),
})

export type PersonUpdatePropertyRequestApi = zod.input<typeof PersonUpdatePropertyRequestApi>
export type PersonUpdatePropertyRequestApiOutput = zod.output<typeof PersonUpdatePropertyRequestApi>

export const personBulkDeleteRequestApiDeleteEventsDefault = false
export const personBulkDeleteRequestApiDeleteRecordingsDefault = false
export const personBulkDeleteRequestApiKeepPersonDefault = false

export const PersonBulkDeleteRequestApi = zod.object({
    ids: zod.array(zod.string()).optional().describe('A list of PostHog person UUIDs to delete (max 1000).'),
    distinct_ids: zod
        .array(zod.string())
        .optional()
        .describe('A list of distinct IDs whose associated persons will be deleted (max 1000).'),
    delete_events: zod
        .boolean()
        .default(personBulkDeleteRequestApiDeleteEventsDefault)
        .describe('If true, queue deletion of all events associated with these persons.'),
    delete_recordings: zod
        .boolean()
        .default(personBulkDeleteRequestApiDeleteRecordingsDefault)
        .describe('If true, queue deletion of all recordings associated with these persons.'),
    keep_person: zod
        .boolean()
        .default(personBulkDeleteRequestApiKeepPersonDefault)
        .describe('If true, keep the person records but delete their events and recordings.'),
})

export type PersonBulkDeleteRequestApi = zod.input<typeof PersonBulkDeleteRequestApi>
export type PersonBulkDeleteRequestApiOutput = zod.output<typeof PersonBulkDeleteRequestApi>

export const PersonBulkDeleteResponseApi = zod.object({
    persons_found: zod.number().describe('Number of persons matched by the provided IDs or distinct IDs.'),
    persons_deleted: zod
        .number()
        .describe('Number of person records deleted from the database. 0 if keep_person was true.'),
    events_queued_for_deletion: zod
        .boolean()
        .describe(
            'Whether event deletion was requested for the matched persons. If a deletion was already queued for a person, it will not be duplicated.'
        ),
    recordings_queued_for_deletion: zod
        .boolean()
        .describe(
            'Whether recording deletion was requested for the matched persons. If a deletion was already queued for a person, it will not be duplicated.'
        ),
    deletion_errors: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe(
            "Persons that could not be deleted. Each entry contains 'person_uuid'. Contact support if this persists."
        ),
})

export type PersonBulkDeleteResponseApi = zod.input<typeof PersonBulkDeleteResponseApi>
export type PersonBulkDeleteResponseApiOutput = zod.output<typeof PersonBulkDeleteResponseApi>

export const AsyncDeletionStatusApi = zod.object({
    person_uuid: zod.string().describe('The UUID of the person whose events are queued for deletion.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the deletion was requested.'),
    status: zod.string().describe("Current status: 'pending' or 'completed'."),
    delete_verified_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the deletion was verified complete. Null if still pending.'),
})

export type AsyncDeletionStatusApi = zod.input<typeof AsyncDeletionStatusApi>
export type AsyncDeletionStatusApiOutput = zod.output<typeof AsyncDeletionStatusApi>

export const PaginatedAsyncDeletionStatusListApi = zod.object({
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    count: zod.number().optional(),
    results: zod.array(AsyncDeletionStatusApi).optional(),
})

export type PaginatedAsyncDeletionStatusListApi = zod.input<typeof PaginatedAsyncDeletionStatusListApi>
export type PaginatedAsyncDeletionStatusListApiOutput = zod.output<typeof PaginatedAsyncDeletionStatusListApi>

export const PersonPropertiesAtTimeMetadataApi = zod
    .object({
        queried_timestamp: zod.string().describe('The timestamp that was queried in ISO format'),
        include_set_once: zod.boolean().describe('Whether $set_once operations were included'),
        distinct_id_used: zod.string().nullable().describe('The distinct_id parameter used in the request'),
        person_id_used: zod.string().nullable().describe('The person_id parameter used in the request'),
        query_mode: zod.string().describe("Whether the query used 'distinct_id' or 'person_id' mode"),
        distinct_ids_queried: zod.array(zod.string()).describe('All distinct_ids that were queried for this person'),
        distinct_ids_count: zod.number().describe('Number of distinct_ids associated with this person'),
    })
    .describe('Serializer for the point-in-time query metadata.')

export type PersonPropertiesAtTimeMetadataApi = zod.input<typeof PersonPropertiesAtTimeMetadataApi>
export type PersonPropertiesAtTimeMetadataApiOutput = zod.output<typeof PersonPropertiesAtTimeMetadataApi>

export const PersonPropertiesAtTimeResponseApi = zod
    .object({
        id: zod.number().describe('The person ID'),
        name: zod.string().describe("The person's display name"),
        distinct_ids: zod.array(zod.string()).describe('All distinct IDs associated with this person'),
        properties: zod
            .record(zod.string(), zod.string().nullable())
            .describe('Person properties as they existed at the specified time'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the person was first created'),
        uuid: zod.uuid().describe("The person's UUID"),
        last_seen_at: zod.iso.datetime({ offset: true }).nullable().describe('When the person was last seen'),
        point_in_time_metadata: PersonPropertiesAtTimeMetadataApi.describe('Metadata about the point-in-time query'),
    })
    .describe('Serializer for the point-in-time person properties response.')

export type PersonPropertiesAtTimeResponseApi = zod.input<typeof PersonPropertiesAtTimeResponseApi>
export type PersonPropertiesAtTimeResponseApiOutput = zod.output<typeof PersonPropertiesAtTimeResponseApi>
