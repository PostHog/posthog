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
    BulkUpdateTagsRequestApi,
    ColumnConfigurationApi,
    ElementApi,
    InsightApi,
    InsightBulkDeleteRequestApi,
    InsightViewedRequestApi,
    PatchedColumnConfigurationApi,
    PatchedElementApi,
    PatchedInsightApi,
} from './api.zod.schemas'

export const ColumnConfigurationsCreateBody = ColumnConfigurationApi

export const ColumnConfigurationsUpdateBody = ColumnConfigurationApi

export const ColumnConfigurationsPartialUpdateBody = PatchedColumnConfigurationApi

export const ElementsCreateBody = ElementApi

export const ElementsUpdateBody = ElementApi

export const ElementsPartialUpdateBody = PatchedElementApi

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.
 *
 * The QueryCoalescingMiddleware attaches cached response data to
 * request.META["_coalesced_response"] for followers. This mixin runs DRF's
 * initial() (auth + permissions + throttling) before returning the
 * cached response, ensuring the request is authorized.
 */
export const InsightsCreateBody = InsightApi

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.
 *
 * The QueryCoalescingMiddleware attaches cached response data to
 * request.META["_coalesced_response"] for followers. This mixin runs DRF's
 * initial() (auth + permissions + throttling) before returning the
 * cached response, ensuring the request is authorized.
 */
export const InsightsUpdateBody = InsightApi

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.
 *
 * The QueryCoalescingMiddleware attaches cached response data to
 * request.META["_coalesced_response"] for followers. This mixin runs DRF's
 * initial() (auth + permissions + throttling) before returning the
 * cached response, ensuring the request is authorized.
 */
export const InsightsPartialUpdateBody = PatchedInsightApi

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.
 *
 * The QueryCoalescingMiddleware attaches cached response data to
 * request.META["_coalesced_response"] for followers. This mixin runs DRF's
 * initial() (auth + permissions + throttling) before returning the
 * cached response, ensuring the request is authorized.
 */
export const InsightsSuggestionsCreateBody = InsightApi

/**
 * Soft-delete insights in bulk by ID. Mirrors the single-insight delete: sets deleted=True, soft-deletes the insights' dashboard tiles, and removes their linked alerts. Insights the requester cannot edit are skipped and reported in `skipped`. Reversible via the bulk_restore endpoint.
 */
export const InsightsBulkDeleteCreateBody = InsightBulkDeleteRequestApi

/**
 * Restore soft-deleted insights in bulk by ID — the inverse of bulk_delete. Sets deleted=False and re-activates the insights' dashboard tiles on dashboards that still exist. Linked alerts are not restored (they are removed on delete). Insights the requester cannot edit are reported in `skipped`.
 */
export const InsightsBulkRestoreCreateBody = InsightBulkDeleteRequestApi

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const InsightsBulkUpdateTagsCreateBody = BulkUpdateTagsRequestApi

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.
 *
 * The QueryCoalescingMiddleware attaches cached response data to
 * request.META["_coalesced_response"] for followers. This mixin runs DRF's
 * initial() (auth + permissions + throttling) before returning the
 * cached response, ensuring the request is authorized.
 */
export const InsightsCancelCreateBody = InsightApi

/**
 * Generate an AI-suggested name and description for an insight based on its query configuration.
 */
export const InsightsGenerateMetadataCreateBody = InsightApi

/**
 * Record that the current user has just viewed one or more insights. Submitted ids that do not belong to the current project or that point at deleted insights are silently dropped. Returns 201 on success regardless of how many ids were retained.
 */
export const InsightsViewedCreateBody = InsightViewedRequestApi
