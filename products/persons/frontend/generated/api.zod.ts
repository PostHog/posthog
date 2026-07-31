/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    PatchedPersonRecordApi,
    PersonBulkDeleteRequestApi,
    PersonDeletePropertyRequestApi,
    PersonRecordApi,
    PersonSplitRequestApi,
    PersonUpdatePropertyRequestApi,
} from './api.zod.schemas'

/**
 * Only for setting properties on the person. "properties" from the request data will be updated via a "$set" event.
 * This means that only the properties listed will be updated, but other properties won't be removed nor updated.
 * If you would like to remove a property use the `delete_property` endpoint.
 */
export const PersonsUpdateBody = PersonRecordApi

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsPartialUpdateBody = PatchedPersonRecordApi

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsDeletePropertyCreateBody = PersonDeletePropertyRequestApi

/**
 * Split distinct_ids off a merged person. Two mutually exclusive modes:
 *
 * - **`distinct_ids_to_split`** (recommended for surgical edits): moves only the listed distinct_ids off this person onto new single-id persons. The original person keeps every other distinct_id and its properties.
 * - **`main_distinct_id`**: keeps only the specified distinct_id on this person; moves every *other* distinct_id off onto its own new person. If omitted, the first distinct_id is kept.
 *
 * The original person always retains its properties. To clear individual properties afterward, use the `delete_property` endpoint.
 *
 * The split runs asynchronously: a 201 response means the task was enqueued. Newly-created split-off persons get a deterministic UUID derived from `(team_id, distinct_id)`, so they can be located client-side without polling. If you need to delete a split-off person after this call, prefer looking it up by that deterministic UUID rather than by distinct_id, since the latter still resolves to the original merged person until the async task completes.
 */
export const PersonsSplitCreateBody = PersonSplitRequestApi

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsUpdatePropertyCreateBody = PersonUpdatePropertyRequestApi

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsBatchByDistinctIdsCreateBody = PersonRecordApi

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsBatchByUuidsCreateBody = PersonRecordApi

/**
 * This endpoint allows you to bulk delete persons, either by the PostHog person IDs or by distinct IDs. You can pass in a maximum of 1000 IDs per call. Only events captured before the request will be deleted.
 */
export const PersonsBulkDeleteCreateBody = PersonBulkDeleteRequestApi

/**
 * Reset a distinct_id for a deleted person. This allows the distinct_id to be used again.
 */
export const PersonsResetPersonDistinctIdCreateBody = PersonRecordApi
