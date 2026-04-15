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

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsPartialUpdateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
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
 * Reset a distinct_id for a deleted person. This allows the distinct_id to be used again.
 */
export const PersonsResetPersonDistinctIdCreateBody = /* @__PURE__ */ zod.object({
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
})
