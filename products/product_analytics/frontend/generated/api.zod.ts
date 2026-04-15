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

export const columnConfigurationsListResponseResultsItemContextKeyMax = 255

export const columnConfigurationsListResponseResultsItemNameMax = 255

export const ColumnConfigurationsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            context_key: zod.string().max(columnConfigurationsListResponseResultsItemContextKeyMax),
            columns: zod.array(zod.string()).optional(),
            name: zod.string().max(columnConfigurationsListResponseResultsItemNameMax).optional(),
            filters: zod.unknown().optional(),
            visibility: zod
                .enum(['private', 'shared'])
                .optional()
                .describe('* `private` - Private (only visible to creator)\n* `shared` - Shared with team'),
            created_by: zod.number().nullable(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
})

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

export const columnConfigurationsRetrieveResponseContextKeyMax = 255

export const columnConfigurationsRetrieveResponseNameMax = 255

export const ColumnConfigurationsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    context_key: zod.string().max(columnConfigurationsRetrieveResponseContextKeyMax),
    columns: zod.array(zod.string()).optional(),
    name: zod.string().max(columnConfigurationsRetrieveResponseNameMax).optional(),
    filters: zod.unknown().optional(),
    visibility: zod
        .enum(['private', 'shared'])
        .optional()
        .describe('* `private` - Private (only visible to creator)\n* `shared` - Shared with team'),
    created_by: zod.number().nullable(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
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

export const columnConfigurationsUpdateResponseContextKeyMax = 255

export const columnConfigurationsUpdateResponseNameMax = 255

export const ColumnConfigurationsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    context_key: zod.string().max(columnConfigurationsUpdateResponseContextKeyMax),
    columns: zod.array(zod.string()).optional(),
    name: zod.string().max(columnConfigurationsUpdateResponseNameMax).optional(),
    filters: zod.unknown().optional(),
    visibility: zod
        .enum(['private', 'shared'])
        .optional()
        .describe('* `private` - Private (only visible to creator)\n* `shared` - Shared with team'),
    created_by: zod.number().nullable(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
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

export const columnConfigurationsPartialUpdateResponseContextKeyMax = 255

export const columnConfigurationsPartialUpdateResponseNameMax = 255

export const ColumnConfigurationsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    context_key: zod.string().max(columnConfigurationsPartialUpdateResponseContextKeyMax),
    columns: zod.array(zod.string()).optional(),
    name: zod.string().max(columnConfigurationsPartialUpdateResponseNameMax).optional(),
    filters: zod.unknown().optional(),
    visibility: zod
        .enum(['private', 'shared'])
        .optional()
        .describe('* `private` - Private (only visible to creator)\n* `shared` - Shared with team'),
    created_by: zod.number().nullable(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const elementsListResponseResultsItemTextMax = 10000

export const elementsListResponseResultsItemTagNameMax = 1000

export const elementsListResponseResultsItemAttrClassItemMax = 200

export const elementsListResponseResultsItemHrefMax = 10000

export const elementsListResponseResultsItemAttrIdMax = 10000

export const elementsListResponseResultsItemNthChildMin = -2147483648
export const elementsListResponseResultsItemNthChildMax = 2147483647

export const elementsListResponseResultsItemNthOfTypeMin = -2147483648
export const elementsListResponseResultsItemNthOfTypeMax = 2147483647

export const elementsListResponseResultsItemOrderMin = -2147483648
export const elementsListResponseResultsItemOrderMax = 2147483647

export const ElementsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            text: zod.string().max(elementsListResponseResultsItemTextMax).nullish(),
            tag_name: zod.string().max(elementsListResponseResultsItemTagNameMax).nullish(),
            attr_class: zod.array(zod.string().max(elementsListResponseResultsItemAttrClassItemMax)).nullish(),
            href: zod.string().max(elementsListResponseResultsItemHrefMax).nullish(),
            attr_id: zod.string().max(elementsListResponseResultsItemAttrIdMax).nullish(),
            nth_child: zod
                .number()
                .min(elementsListResponseResultsItemNthChildMin)
                .max(elementsListResponseResultsItemNthChildMax)
                .nullish(),
            nth_of_type: zod
                .number()
                .min(elementsListResponseResultsItemNthOfTypeMin)
                .max(elementsListResponseResultsItemNthOfTypeMax)
                .nullish(),
            attributes: zod.unknown().optional(),
            order: zod
                .number()
                .min(elementsListResponseResultsItemOrderMin)
                .max(elementsListResponseResultsItemOrderMax)
                .nullish(),
        })
    ),
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

export const elementsRetrieveResponseTextMax = 10000

export const elementsRetrieveResponseTagNameMax = 1000

export const elementsRetrieveResponseAttrClassItemMax = 200

export const elementsRetrieveResponseHrefMax = 10000

export const elementsRetrieveResponseAttrIdMax = 10000

export const elementsRetrieveResponseNthChildMin = -2147483648
export const elementsRetrieveResponseNthChildMax = 2147483647

export const elementsRetrieveResponseNthOfTypeMin = -2147483648
export const elementsRetrieveResponseNthOfTypeMax = 2147483647

export const elementsRetrieveResponseOrderMin = -2147483648
export const elementsRetrieveResponseOrderMax = 2147483647

export const ElementsRetrieveResponse = /* @__PURE__ */ zod.object({
    text: zod.string().max(elementsRetrieveResponseTextMax).nullish(),
    tag_name: zod.string().max(elementsRetrieveResponseTagNameMax).nullish(),
    attr_class: zod.array(zod.string().max(elementsRetrieveResponseAttrClassItemMax)).nullish(),
    href: zod.string().max(elementsRetrieveResponseHrefMax).nullish(),
    attr_id: zod.string().max(elementsRetrieveResponseAttrIdMax).nullish(),
    nth_child: zod.number().min(elementsRetrieveResponseNthChildMin).max(elementsRetrieveResponseNthChildMax).nullish(),
    nth_of_type: zod
        .number()
        .min(elementsRetrieveResponseNthOfTypeMin)
        .max(elementsRetrieveResponseNthOfTypeMax)
        .nullish(),
    attributes: zod.unknown().optional(),
    order: zod.number().min(elementsRetrieveResponseOrderMin).max(elementsRetrieveResponseOrderMax).nullish(),
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

export const elementsUpdateResponseTextMax = 10000

export const elementsUpdateResponseTagNameMax = 1000

export const elementsUpdateResponseAttrClassItemMax = 200

export const elementsUpdateResponseHrefMax = 10000

export const elementsUpdateResponseAttrIdMax = 10000

export const elementsUpdateResponseNthChildMin = -2147483648
export const elementsUpdateResponseNthChildMax = 2147483647

export const elementsUpdateResponseNthOfTypeMin = -2147483648
export const elementsUpdateResponseNthOfTypeMax = 2147483647

export const elementsUpdateResponseOrderMin = -2147483648
export const elementsUpdateResponseOrderMax = 2147483647

export const ElementsUpdateResponse = /* @__PURE__ */ zod.object({
    text: zod.string().max(elementsUpdateResponseTextMax).nullish(),
    tag_name: zod.string().max(elementsUpdateResponseTagNameMax).nullish(),
    attr_class: zod.array(zod.string().max(elementsUpdateResponseAttrClassItemMax)).nullish(),
    href: zod.string().max(elementsUpdateResponseHrefMax).nullish(),
    attr_id: zod.string().max(elementsUpdateResponseAttrIdMax).nullish(),
    nth_child: zod.number().min(elementsUpdateResponseNthChildMin).max(elementsUpdateResponseNthChildMax).nullish(),
    nth_of_type: zod.number().min(elementsUpdateResponseNthOfTypeMin).max(elementsUpdateResponseNthOfTypeMax).nullish(),
    attributes: zod.unknown().optional(),
    order: zod.number().min(elementsUpdateResponseOrderMin).max(elementsUpdateResponseOrderMax).nullish(),
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

export const elementsPartialUpdateResponseTextMax = 10000

export const elementsPartialUpdateResponseTagNameMax = 1000

export const elementsPartialUpdateResponseAttrClassItemMax = 200

export const elementsPartialUpdateResponseHrefMax = 10000

export const elementsPartialUpdateResponseAttrIdMax = 10000

export const elementsPartialUpdateResponseNthChildMin = -2147483648
export const elementsPartialUpdateResponseNthChildMax = 2147483647

export const elementsPartialUpdateResponseNthOfTypeMin = -2147483648
export const elementsPartialUpdateResponseNthOfTypeMax = 2147483647

export const elementsPartialUpdateResponseOrderMin = -2147483648
export const elementsPartialUpdateResponseOrderMax = 2147483647

export const ElementsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    text: zod.string().max(elementsPartialUpdateResponseTextMax).nullish(),
    tag_name: zod.string().max(elementsPartialUpdateResponseTagNameMax).nullish(),
    attr_class: zod.array(zod.string().max(elementsPartialUpdateResponseAttrClassItemMax)).nullish(),
    href: zod.string().max(elementsPartialUpdateResponseHrefMax).nullish(),
    attr_id: zod.string().max(elementsPartialUpdateResponseAttrIdMax).nullish(),
    nth_child: zod
        .number()
        .min(elementsPartialUpdateResponseNthChildMin)
        .max(elementsPartialUpdateResponseNthChildMax)
        .nullish(),
    nth_of_type: zod
        .number()
        .min(elementsPartialUpdateResponseNthOfTypeMin)
        .max(elementsPartialUpdateResponseNthOfTypeMax)
        .nullish(),
    attributes: zod.unknown().optional(),
    order: zod.number().min(elementsPartialUpdateResponseOrderMin).max(elementsPartialUpdateResponseOrderMax).nullish(),
})

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const InsightsListResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

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
export const InsightsRetrieveResponse = /* @__PURE__ */ zod
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

export const InsightsUpdateResponse = /* @__PURE__ */ zod
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

export const InsightsPartialUpdateResponse = /* @__PURE__ */ zod
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
