/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsListResponse = /* @__PURE__ */ zod.object({
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    count: zod.number().optional(),
    results: zod
        .array(
            zod.object({
                id: zod.number().describe('Numeric person ID.'),
                name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
                distinct_ids: zod.array(zod.string()),
                properties: zod
                    .unknown()
                    .optional()
                    .describe('Key-value map of person properties set via $set and $set_once operations.'),
                created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
                uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
                last_seen_at: zod.iso
                    .datetime({})
                    .nullable()
                    .describe('Timestamp of the last event from this person, or null.'),
            })
        )
        .optional(),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.number().describe('Numeric person ID.'),
    name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
    distinct_ids: zod.array(zod.string()),
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
    created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
    uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
    last_seen_at: zod.iso.datetime({}).nullable().describe('Timestamp of the last event from this person, or null.'),
})

/**
 * Only for setting properties on the person. "properties" from the request data will be updated via a "$set" event.
This means that only the properties listed will be updated, but other properties won't be removed nor updated.
If you would like to remove a property use the `delete_property` endpoint.
 */
export const PersonsUpdateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
})

export const PersonsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number().describe('Numeric person ID.'),
    name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
    distinct_ids: zod.array(zod.string()),
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
    created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
    uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
    last_seen_at: zod.iso.datetime({}).nullable().describe('Timestamp of the last event from this person, or null.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsPartialUpdateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
})

export const PersonsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number().describe('Numeric person ID.'),
    name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
    distinct_ids: zod.array(zod.string()),
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
    created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
    uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
    last_seen_at: zod.iso.datetime({}).nullable().describe('Timestamp of the last event from this person, or null.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsDeletePropertyCreateBody = /* @__PURE__ */ zod.object({
    $unset: zod.string().describe('The property key to remove from this person.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsSplitCreateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsUpdatePropertyCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().describe('The property key to set.'),
    value: zod.unknown().describe('The property value. Can be a string, number, boolean, or object.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsBatchByDistinctIdsCreateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsBatchByUuidsCreateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
})

/**
 * This endpoint allows you to bulk delete persons, either by the PostHog person IDs or by distinct IDs. You can pass in a maximum of 1000 IDs per call. Only events captured before the request will be deleted.
 */
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
export const PersonsFunnelCreateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsFunnelCorrelationCreateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
})

/**
 * Get person properties as they existed at a specific point in time.

This endpoint reconstructs person properties by querying ClickHouse events
for $set and $set_once operations up to the specified timestamp.

Query parameters:
- distinct_id: The distinct_id of the person
- timestamp: ISO datetime string for the point in time (e.g., "2023-06-15T14:30:00Z")
- include_set_once: Whether to handle $set_once operations (default: false)
- debug: Whether to include debug information with raw events (default: false)
 */
export const PersonsPropertiesAtTimeRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number().describe('The person ID'),
        name: zod.string().describe("The person's display name"),
        distinct_ids: zod.array(zod.string()).describe('All distinct IDs associated with this person'),
        properties: zod
            .record(zod.string(), zod.string().nullable())
            .describe('Person properties as they existed at the specified time'),
        created_at: zod.iso.datetime({}).describe('When the person was first created'),
        uuid: zod.uuid().describe("The person's UUID"),
        last_seen_at: zod.iso.datetime({}).nullable().describe('When the person was last seen'),
        point_in_time_metadata: zod
            .object({
                queried_timestamp: zod.string().describe('The timestamp that was queried in ISO format'),
                include_set_once: zod.boolean().describe('Whether $set_once operations were included'),
                distinct_id_used: zod.string().nullable().describe('The distinct_id parameter used in the request'),
                person_id_used: zod.string().nullable().describe('The person_id parameter used in the request'),
                query_mode: zod.string().describe("Whether the query used 'distinct_id' or 'person_id' mode"),
                distinct_ids_queried: zod
                    .array(zod.string())
                    .describe('All distinct_ids that were queried for this person'),
                distinct_ids_count: zod.number().describe('Number of distinct_ids associated with this person'),
            })
            .describe('Serializer for the point-in-time query metadata.')
            .describe('Metadata about the point-in-time query'),
        debug: zod
            .object({
                query: zod.string().describe('The ClickHouse query that was executed'),
                params: zod.record(zod.string(), zod.unknown()).describe('The parameters passed to the query'),
                events_found: zod.number().describe('Number of events found'),
                events: zod
                    .array(zod.record(zod.string(), zod.unknown()))
                    .describe('Raw events that were used to build the properties'),
                error: zod.string().optional().describe('Error message if debug query failed'),
            })
            .describe('Serializer for the debug information (only available to staff users).')
            .optional()
            .describe('Debug information (only available when debug=true and DEBUG=True)'),
    })
    .describe('Serializer for the point-in-time person properties response.')

/**
 * Reset a distinct_id for a deleted person. This allows the distinct_id to be used again.
 */
export const PersonsResetPersonDistinctIdCreateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
})
