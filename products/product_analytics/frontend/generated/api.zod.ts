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
 * Sets how long every project without its own window keeps events. Events older than the window are deleted on the next monthly cleanup and can't be restored. Organization admins only.
 * @summary Set the organization's events retention window
 */

export const OrganizationEventsRetentionUpdateBody = /* @__PURE__ */ zod.object({
    retention_months: zod
        .number()
        .min(1)
        .nullable()
        .describe(
            "The window in months. Events older than this are deleted on the next monthly cleanup and can't be restored. Null removes the window."
        ),
})

export const columnConfigurationsCreateBodyContextKeyMax = 255

export const columnConfigurationsCreateBodyNameMax = 255

export const ColumnConfigurationsCreateBody = /* @__PURE__ */ zod.object({
    context_key: zod.string().max(columnConfigurationsCreateBodyContextKeyMax),
    columns: zod.array(zod.string()).optional(),
    name: zod.string().max(columnConfigurationsCreateBodyNameMax).optional(),
    filters: zod.unknown().optional().describe('Column filter state persisted with this view configuration.'),
    order_by: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Ordered list of HogQL expressions describing the table sort. Null preserves the current sort on apply (legacy rows); an empty list explicitly means no sort.'
        ),
    properties: zod
        .unknown()
        .optional()
        .describe(
            'Product-specific view state that does not fit the columnar fields (e.g. Customer analytics overview tiles and column display).'
        ),
    visibility: zod
        .enum(['private', 'shared'])
        .optional()
        .describe('\* `private` - Private (only visible to creator)\n\* `shared` - Shared with team'),
})

export const columnConfigurationsUpdateBodyContextKeyMax = 255

export const columnConfigurationsUpdateBodyNameMax = 255

export const ColumnConfigurationsUpdateBody = /* @__PURE__ */ zod.object({
    context_key: zod.string().max(columnConfigurationsUpdateBodyContextKeyMax),
    columns: zod.array(zod.string()).optional(),
    name: zod.string().max(columnConfigurationsUpdateBodyNameMax).optional(),
    filters: zod.unknown().optional().describe('Column filter state persisted with this view configuration.'),
    order_by: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Ordered list of HogQL expressions describing the table sort. Null preserves the current sort on apply (legacy rows); an empty list explicitly means no sort.'
        ),
    properties: zod
        .unknown()
        .optional()
        .describe(
            'Product-specific view state that does not fit the columnar fields (e.g. Customer analytics overview tiles and column display).'
        ),
    visibility: zod
        .enum(['private', 'shared'])
        .optional()
        .describe('\* `private` - Private (only visible to creator)\n\* `shared` - Shared with team'),
})

export const columnConfigurationsPartialUpdateBodyContextKeyMax = 255

export const columnConfigurationsPartialUpdateBodyNameMax = 255

export const ColumnConfigurationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    context_key: zod.string().max(columnConfigurationsPartialUpdateBodyContextKeyMax).optional(),
    columns: zod.array(zod.string()).optional(),
    name: zod.string().max(columnConfigurationsPartialUpdateBodyNameMax).optional(),
    filters: zod.unknown().optional().describe('Column filter state persisted with this view configuration.'),
    order_by: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Ordered list of HogQL expressions describing the table sort. Null preserves the current sort on apply (legacy rows); an empty list explicitly means no sort.'
        ),
    properties: zod
        .unknown()
        .optional()
        .describe(
            'Product-specific view state that does not fit the columnar fields (e.g. Customer analytics overview tiles and column display).'
        ),
    visibility: zod
        .enum(['private', 'shared'])
        .optional()
        .describe('\* `private` - Private (only visible to creator)\n\* `shared` - Shared with team'),
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
 * Sets how long this project keeps events, overriding the organization's window. Events older than the window are deleted on the next monthly cleanup and can't be restored. Organization admins only.
 * @summary Set the events retention window for a project
 */

export const EventsRetentionUpdateBody = /* @__PURE__ */ zod.object({
    retention_months: zod
        .number()
        .min(1)
        .nullable()
        .describe(
            "The window in months. Events older than this are deleted on the next monthly cleanup and can't be restored. Null removes the window."
        ),
})

export const InsightsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const InsightsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const InsightsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Soft-delete insights in bulk by ID. Mirrors the single-insight delete: sets deleted=True, soft-deletes the insights' dashboard tiles, and removes their linked alerts. Insights the requester cannot edit are skipped and reported in `skipped`. Reversible via the bulk_restore endpoint.
 */

export const insightsBulkDeleteCreateBodyIdsMax = 1000

export const InsightsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number().min(1))
        .max(insightsBulkDeleteCreateBodyIdsMax)
        .describe(
            'Insight IDs to soft-delete (or restore). At most 1000 ids per request. Soft-deleted insights can be brought back via the bulk_restore endpoint.'
        ),
})

/**
 * Restore soft-deleted insights in bulk by ID — the inverse of bulk_delete. Sets deleted=False and re-activates the insights' dashboard tiles on dashboards that still exist. Linked alerts are not restored (they are removed on delete). Insights the requester cannot edit are reported in `skipped`.
 */

export const insightsBulkRestoreCreateBodyIdsMax = 1000

export const InsightsBulkRestoreCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number().min(1))
        .max(insightsBulkRestoreCreateBodyIdsMax)
        .describe(
            'Insight IDs to soft-delete (or restore). At most 1000 ids per request. Soft-deleted insights can be brought back via the bulk_restore endpoint.'
        ),
})

/**
 * Turn 'filter out internal and test users' on or off for every existing insight in the project. Requires project admin, matching the settings UI that fronts it. The setting of the same name only decides the default for new insights; this applies it to the insights that already exist. Only insights that store a query are changed; insights still holding legacy `filters` are counted in `legacy` and left as they are. Insights with nowhere to put the toggle, such as SQL insights, are left alone, as are insights the requester cannot edit. Dashboards follow their insights unless the dashboard sets its own override. Insights are updated in batches, so a failure part way through leaves the finished batches applied. Retrying is safe and picks up the rest.
 */
export const InsightsBulkSetTestAccountFilterCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().describe('Whether every existing insight should filter out internal and test users.'),
})

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
export const insightsBulkUpdateTagsCreateBodyIdsMax = 500

export const insightsBulkUpdateTagsCreateBodyTagsItemMax = 255

export const insightsBulkUpdateTagsCreateBodyTagsMax = 100

export const InsightsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(insightsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
        ),
    tags: zod
        .array(zod.string().max(insightsBulkUpdateTagsCreateBodyTagsItemMax))
        .max(insightsBulkUpdateTagsCreateBodyTagsMax)
        .describe('Tag names to add, remove, or set (up to 100 per request, 255 characters each).'),
})

export const InsightsCancelCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Check the events behind an insight for the common ways they mislead: internal and test users, local development traffic, bots and crawlers, and events sent twice. Works for trends, funnels, stickiness and lifecycle insights whose series are events. The checks apply the insight's own filters, and read the newest days of its date range, up to 7. The bot and duplicate checks read a sample of those days. For a token, the internal users check matches the emails of the organization's members only with the `organization_member:read` scope, and its verified domains only with `organization:read`. It names the emails it finds only with `person:read`. Nothing is stored. This route runs the query it is sent, so it needs query access as well as insight access. To check a saved insight by its id, send a GET request to `insights/{id}/data_checks/`.
 */
export const InsightsDataChecksCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Classify what most likely caused each moment on a chart. The caller sends chapters of facts that it computed from the chart's data, and gets back one cause from a fixed list for each chapter, with a confidence. The numbers stay with the caller: this endpoint runs no query and reads no insight. Without a decision model on the instance, the list is empty. The organization must approve AI data processing.
 */
export const insightsExplainCreateBodySeriesLabelMax = 200

export const insightsExplainCreateBodyInsightNameDefault = ``
export const insightsExplainCreateBodyInsightNameMax = 400

export const insightsExplainCreateBodyOverviewDefault = ``
export const insightsExplainCreateBodyOverviewMax = 600

export const insightsExplainCreateBodyChaptersItemIdMax = 64

export const insightsExplainCreateBodyChaptersItemTitleMax = 200

export const insightsExplainCreateBodyChaptersItemSummaryMax = 600

export const insightsExplainCreateBodyChaptersItemEvidenceItemMax = 600

export const insightsExplainCreateBodyChaptersItemEvidenceMax = 6

export const insightsExplainCreateBodyChaptersMax = 8

export const InsightsExplainCreateBody = /* @__PURE__ */ zod.object({
    series_label: zod
        .string()
        .max(insightsExplainCreateBodySeriesLabelMax)
        .describe('Name of the series that the explanation follows.'),
    insight_name: zod
        .string()
        .max(insightsExplainCreateBodyInsightNameMax)
        .default(insightsExplainCreateBodyInsightNameDefault)
        .describe('Name of the insight. Blank for an insight that has no name yet.'),
    overview: zod
        .string()
        .max(insightsExplainCreateBodyOverviewMax)
        .default(insightsExplainCreateBodyOverviewDefault)
        .describe('The computed facts of the whole chart, such as its typical level, its range and how it ends.'),
    chapters: zod
        .array(
            zod.object({
                id: zod
                    .string()
                    .max(insightsExplainCreateBodyChaptersItemIdMax)
                    .describe('Identifier of the chapter. The response returns the chapter under the same one.'),
                title: zod
                    .string()
                    .max(insightsExplainCreateBodyChaptersItemTitleMax)
                    .describe("What the chapter is about, for example 'A peak on October 2'."),
                summary: zod
                    .string()
                    .max(insightsExplainCreateBodyChaptersItemSummaryMax)
                    .describe(
                        'The computed facts of the chapter in one or two sentences, with their numbers and dates.'
                    ),
                evidence: zod
                    .array(zod.string().max(insightsExplainCreateBodyChaptersItemEvidenceItemMax))
                    .max(insightsExplainCreateBodyChaptersItemEvidenceMax)
                    .optional()
                    .describe(
                        'Findings about the cause of the chapter, one sentence each. Empty when nothing was found. At most 6.'
                    ),
            })
        )
        .max(insightsExplainCreateBodyChaptersMax)
        .describe(
            'The chapters of the explanation in reading order. At most 8. Empty when nothing stands out on the chart.'
        ),
})

/**
 * Generate an AI-suggested name and description for an insight based on its query configuration.
 */
export const InsightsGenerateMetadataCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Record that the current user has just viewed one or more insights. Submitted ids that do not belong to the current project or that point at deleted insights are silently dropped, as are views from impersonated staff-support sessions. Returns 201 on success regardless of how many ids were retained.
 */
export const insightsViewedCreateBodyInsightIdsMax = 2500

export const InsightsViewedCreateBody = /* @__PURE__ */ zod.object({
    insight_ids: zod
        .array(zod.number())
        .max(insightsViewedCreateBodyInsightIdsMax)
        .describe('Insight IDs that were just viewed by the current user. At most 2500 ids per request.'),
})

/**
 * Converts a displayed journeys segment into the funnel query that reproduces its unique-actor count exactly. In open mode only a single edge converts (a two-step funnel with the inactivity gap as conversion window); in anchored mode any anchor-rooted chain converts (window W). The funnel is returned as JSON and is not executed or persisted here.
 * @summary Convert a journey segment to a funnel
 */
export const PathsV2SegmentToFunnelCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .unknown()
        .describe(
            'The PathsV2Query the segment is displayed under (JSON object with kind `PathsV2Query`). Step sources, path cleaning, excluded items, date range, and the gap or conversion window are read from it, so the emitted funnel counts exactly what the chart shows.'
        ),
    items: zod
        .array(
            zod.object({
                event: zod.string().describe('Event of the step source this path item belongs to.'),
                label: zod
                    .string()
                    .nullish()
                    .describe(
                        "Label value from the source's naming property, after path cleaning. Null or omitted for sources without a naming property; an empty string means the property was missing on the event."
                    ),
            })
        )
        .describe(
            "The segment's path items in displayed order. In open mode exactly two items - a single edge, source then target. In anchored mode the concrete chain as shown, starting at the anchor."
        ),
})
