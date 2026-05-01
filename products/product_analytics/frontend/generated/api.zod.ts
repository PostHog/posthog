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

export const columnConfigurationsCreateBodyContextKeyMax = 255

export const columnConfigurationsCreateBodyNameMax = 255

export const ColumnConfigurationsCreateBody = /* @__PURE__ */ zod.object({
    context_key: zod.string().max(columnConfigurationsCreateBodyContextKeyMax),
    columns: zod.array(zod.string()).optional(),
    name: zod.string().max(columnConfigurationsCreateBodyNameMax).optional(),
    filters: zod.unknown().optional(),
    visibility: zod
        .enum(['private', 'shared'])
        .optional()
        .describe('* `private` - Private (only visible to creator)\n* `shared` - Shared with team'),
})

export const columnConfigurationsUpdateBodyContextKeyMax = 255

export const columnConfigurationsUpdateBodyNameMax = 255

export const ColumnConfigurationsUpdateBody = /* @__PURE__ */ zod.object({
    context_key: zod.string().max(columnConfigurationsUpdateBodyContextKeyMax),
    columns: zod.array(zod.string()).optional(),
    name: zod.string().max(columnConfigurationsUpdateBodyNameMax).optional(),
    filters: zod.unknown().optional(),
    visibility: zod
        .enum(['private', 'shared'])
        .optional()
        .describe('* `private` - Private (only visible to creator)\n* `shared` - Shared with team'),
})

export const columnConfigurationsPartialUpdateBodyContextKeyMax = 255

export const columnConfigurationsPartialUpdateBodyNameMax = 255

export const ColumnConfigurationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    context_key: zod.string().max(columnConfigurationsPartialUpdateBodyContextKeyMax).optional(),
    columns: zod.array(zod.string()).optional(),
    name: zod.string().max(columnConfigurationsPartialUpdateBodyNameMax).optional(),
    filters: zod.unknown().optional(),
    visibility: zod
        .enum(['private', 'shared'])
        .optional()
        .describe('* `private` - Private (only visible to creator)\n* `shared` - Shared with team'),
})

export const elementsCreateBodyTextMax = 10000

export const elementsCreateBodyTagNameMax = 1000

export const elementsCreateBodyAttrClassItemMax = 200

export const elementsCreateBodyHrefMax = 10000

export const elementsCreateBodyAttrIdMax = 10000

export const elementsCreateBodyNthChildMin = -2147483648
export const elementsCreateBodyNthChildMax = 2147483647

export const elementsCreateBodyNthOfTypeMin = -2147483648
export const elementsCreateBodyNthOfTypeMax = 2147483647

export const elementsCreateBodyOrderMin = -2147483648
export const elementsCreateBodyOrderMax = 2147483647

export const ElementsCreateBody = /* @__PURE__ */ zod.object({
    text: zod.string().max(elementsCreateBodyTextMax).nullish(),
    tag_name: zod.string().max(elementsCreateBodyTagNameMax).nullish(),
    attr_class: zod.array(zod.string().max(elementsCreateBodyAttrClassItemMax)).nullish(),
    href: zod.string().max(elementsCreateBodyHrefMax).nullish(),
    attr_id: zod.string().max(elementsCreateBodyAttrIdMax).nullish(),
    nth_child: zod.number().min(elementsCreateBodyNthChildMin).max(elementsCreateBodyNthChildMax).nullish(),
    nth_of_type: zod.number().min(elementsCreateBodyNthOfTypeMin).max(elementsCreateBodyNthOfTypeMax).nullish(),
    attributes: zod.unknown().optional(),
    order: zod.number().min(elementsCreateBodyOrderMin).max(elementsCreateBodyOrderMax).nullish(),
})

export const elementsUpdateBodyTextMax = 10000

export const elementsUpdateBodyTagNameMax = 1000

export const elementsUpdateBodyAttrClassItemMax = 200

export const elementsUpdateBodyHrefMax = 10000

export const elementsUpdateBodyAttrIdMax = 10000

export const elementsUpdateBodyNthChildMin = -2147483648
export const elementsUpdateBodyNthChildMax = 2147483647

export const elementsUpdateBodyNthOfTypeMin = -2147483648
export const elementsUpdateBodyNthOfTypeMax = 2147483647

export const elementsUpdateBodyOrderMin = -2147483648
export const elementsUpdateBodyOrderMax = 2147483647

export const ElementsUpdateBody = /* @__PURE__ */ zod.object({
    text: zod.string().max(elementsUpdateBodyTextMax).nullish(),
    tag_name: zod.string().max(elementsUpdateBodyTagNameMax).nullish(),
    attr_class: zod.array(zod.string().max(elementsUpdateBodyAttrClassItemMax)).nullish(),
    href: zod.string().max(elementsUpdateBodyHrefMax).nullish(),
    attr_id: zod.string().max(elementsUpdateBodyAttrIdMax).nullish(),
    nth_child: zod.number().min(elementsUpdateBodyNthChildMin).max(elementsUpdateBodyNthChildMax).nullish(),
    nth_of_type: zod.number().min(elementsUpdateBodyNthOfTypeMin).max(elementsUpdateBodyNthOfTypeMax).nullish(),
    attributes: zod.unknown().optional(),
    order: zod.number().min(elementsUpdateBodyOrderMin).max(elementsUpdateBodyOrderMax).nullish(),
})

export const elementsPartialUpdateBodyTextMax = 10000

export const elementsPartialUpdateBodyTagNameMax = 1000

export const elementsPartialUpdateBodyAttrClassItemMax = 200

export const elementsPartialUpdateBodyHrefMax = 10000

export const elementsPartialUpdateBodyAttrIdMax = 10000

export const elementsPartialUpdateBodyNthChildMin = -2147483648
export const elementsPartialUpdateBodyNthChildMax = 2147483647

export const elementsPartialUpdateBodyNthOfTypeMin = -2147483648
export const elementsPartialUpdateBodyNthOfTypeMax = 2147483647

export const elementsPartialUpdateBodyOrderMin = -2147483648
export const elementsPartialUpdateBodyOrderMax = 2147483647

export const ElementsPartialUpdateBody = /* @__PURE__ */ zod.object({
    text: zod.string().max(elementsPartialUpdateBodyTextMax).nullish(),
    tag_name: zod.string().max(elementsPartialUpdateBodyTagNameMax).nullish(),
    attr_class: zod.array(zod.string().max(elementsPartialUpdateBodyAttrClassItemMax)).nullish(),
    href: zod.string().max(elementsPartialUpdateBodyHrefMax).nullish(),
    attr_id: zod.string().max(elementsPartialUpdateBodyAttrIdMax).nullish(),
    nth_child: zod
        .number()
        .min(elementsPartialUpdateBodyNthChildMin)
        .max(elementsPartialUpdateBodyNthChildMax)
        .nullish(),
    nth_of_type: zod
        .number()
        .min(elementsPartialUpdateBodyNthOfTypeMin)
        .max(elementsPartialUpdateBodyNthOfTypeMax)
        .nullish(),
    attributes: zod.unknown().optional(),
    order: zod.number().min(elementsPartialUpdateBodyOrderMin).max(elementsPartialUpdateBodyOrderMax).nullish(),
})

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const InsightsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const InsightsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const InsightsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const InsightsSuggestionsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const insightsBulkUpdateTagsCreateBodyIdsMax = 500

export const InsightsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(insightsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('* `add` - add\n* `remove` - remove\n* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n* `add` - add\n* `remove` - remove\n* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const InsightsCancelCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Generate an AI-suggested name and description for an insight based on its query configuration.
 */
export const InsightsGenerateMetadataCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Update insight view timestamps.
Expects: {"insight_ids": [1, 2, 3, ...]}
 */
export const InsightsViewedCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')
