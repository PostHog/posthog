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
 * Create a saved heatmap for a page URL. For type 'screenshot' (the default) this enqueues a headless render of the page at each target width; poll the saved heatmap or its content endpoint until status is 'completed'. Provide 'widths' to control which viewport widths are rendered.
 */
export const savedCreateBodyNameMax = 400

export const savedCreateBodyUrlMax = 2000

export const savedCreateBodyDataUrlMax = 2000

export const savedCreateBodyWidthsItemMin = 100
export const savedCreateBodyWidthsItemMax = 3000

export const savedCreateBodyWidthsMax = 16

export const savedCreateBodyTypeDefault = `screenshot`

export const SavedCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(savedCreateBodyNameMax).nullish().describe('Human-readable label for the saved heatmap.'),
    url: zod
        .url()
        .max(savedCreateBodyUrlMax)
        .describe('Exact page URL to render and overlay heatmap data on. Wildcards are not allowed.'),
    data_url: zod
        .url()
        .max(savedCreateBodyDataUrlMax)
        .nullish()
        .describe("URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted."),
    widths: zod
        .array(zod.number().min(savedCreateBodyWidthsItemMin).max(savedCreateBodyWidthsItemMax))
        .max(savedCreateBodyWidthsMax)
        .optional()
        .describe(
            'Viewport widths (px, 100-3000) to render the heatmap screenshot at — one render per width. Defaults to [320, 375, 425, 768, 1024, 1440, 1920] when omitted. At most 16 widths.'
        ),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .describe('\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording')
        .default(savedCreateBodyTypeDefault)
        .describe(
            "Render mode: 'screenshot' (renders the page headlessly, default), 'iframe', or 'recording'. Only 'screenshot' generates image bytes.\n\n\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording"
        ),
    deleted: zod.boolean().optional().describe('Set true to soft-delete the saved heatmap.'),
    block_consent_modals: zod
        .boolean()
        .optional()
        .describe(
            "When true, ask the headless browser to dismiss cookie\/consent banners before capturing the screenshot. Off by default: the blocker can stall the render on some sites and time out. Only applies to 'screenshot' heatmaps."
        ),
})

/**
 * Update a saved heatmap (e.g. rename, change widths, or soft-delete via 'deleted'). Changing the URL of a 'screenshot' heatmap triggers a re-render.
 */
export const savedPartialUpdateBodyNameMax = 400

export const savedPartialUpdateBodyUrlMax = 2000

export const savedPartialUpdateBodyDataUrlMax = 2000

export const savedPartialUpdateBodyWidthsItemMin = 100
export const savedPartialUpdateBodyWidthsItemMax = 3000

export const savedPartialUpdateBodyWidthsMax = 16

export const savedPartialUpdateBodyTypeDefault = `screenshot`

export const SavedPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(savedPartialUpdateBodyNameMax)
        .nullish()
        .describe('Human-readable label for the saved heatmap.'),
    url: zod
        .url()
        .max(savedPartialUpdateBodyUrlMax)
        .optional()
        .describe('Exact page URL to render and overlay heatmap data on. Wildcards are not allowed.'),
    data_url: zod
        .url()
        .max(savedPartialUpdateBodyDataUrlMax)
        .nullish()
        .describe("URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted."),
    widths: zod
        .array(zod.number().min(savedPartialUpdateBodyWidthsItemMin).max(savedPartialUpdateBodyWidthsItemMax))
        .max(savedPartialUpdateBodyWidthsMax)
        .optional()
        .describe(
            'Viewport widths (px, 100-3000) to render the heatmap screenshot at — one render per width. Defaults to [320, 375, 425, 768, 1024, 1440, 1920] when omitted. At most 16 widths.'
        ),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .describe('\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording')
        .default(savedPartialUpdateBodyTypeDefault)
        .describe(
            "Render mode: 'screenshot' (renders the page headlessly, default), 'iframe', or 'recording'. Only 'screenshot' generates image bytes.\n\n\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording"
        ),
    deleted: zod.boolean().optional().describe('Set true to soft-delete the saved heatmap.'),
    block_consent_modals: zod
        .boolean()
        .optional()
        .describe(
            "When true, ask the headless browser to dismiss cookie\/consent banners before capturing the screenshot. Off by default: the blocker can stall the render on some sites and time out. Only applies to 'screenshot' heatmaps."
        ),
})

/**
 * Persist screenshots captured client-side by the on-page toolbar as a completed screenshot heatmap. No headless render is enqueued: the toolbar runs in the user's authenticated browser, so this is the path for pages behind a login that Browserless cannot reach. Send one 'image'+'width', or 'images'+'widths' parallel arrays to store several viewport widths on one heatmap (the toolbar re-lays out the page at each width and captures it, matching the widths the server renders). The image bytes are stored and served only through the authenticated content endpoint. The heatmap's data URL is set to the captured URL.
 */
export const savedCaptureCreateBodyWidthMin = 100
export const savedCaptureCreateBodyWidthMax = 3000

export const savedCaptureCreateBodyImagesMax = 16

export const savedCaptureCreateBodyWidthsItemMin = 100
export const savedCaptureCreateBodyWidthsItemMax = 3000

export const savedCaptureCreateBodyWidthsMax = 16

export const savedCaptureCreateBodyUrlMax = 2000

export const savedCaptureCreateBodyNameMax = 400

export const SavedCaptureCreateBody = /* @__PURE__ */ zod.object({
    image: zod
        .url()
        .optional()
        .describe(
            "Single screenshot of the page, captured client-side by the toolbar (JPEG or PNG). Max 20MB. Pair with 'width'. Use 'images'\/'widths' instead to save several viewport widths on one heatmap."
        ),
    width: zod
        .number()
        .min(savedCaptureCreateBodyWidthMin)
        .max(savedCaptureCreateBodyWidthMax)
        .optional()
        .describe("Viewport width (CSS pixels) the single 'image' was captured at."),
    images: zod
        .array(zod.url())
        .max(savedCaptureCreateBodyImagesMax)
        .optional()
        .describe(
            "One screenshot per viewport width, parallel to 'widths' (same length, same order). Lets a single toolbar capture cover the same viewport widths the server renders. At most 16 widths."
        ),
    widths: zod
        .array(zod.number().min(savedCaptureCreateBodyWidthsItemMin).max(savedCaptureCreateBodyWidthsItemMax))
        .max(savedCaptureCreateBodyWidthsMax)
        .optional()
        .describe("Viewport widths (CSS pixels) the 'images' were captured at, parallel to 'images'."),
    url: zod
        .string()
        .max(savedCaptureCreateBodyUrlMax)
        .describe(
            'Exact page URL the screenshot was captured on. Wildcards are not allowed; this is stored as both the heatmap URL and its data URL, so the overlay reads aggregate data for this exact URL.'
        ),
    name: zod
        .string()
        .max(savedCaptureCreateBodyNameMax)
        .optional()
        .describe('Human-readable label for the saved heatmap. Defaults to the URL when omitted.'),
})

/**
 * Fetch a page URL server-side and report whether it allows being embedded in the live preview iframe, plus the HTTP status it returned. The live preview loads the customer's site directly in their browser, so a site that sends X-Frame-Options or a restrictive frame-ancestors will never render, and a 4xx or 5xx from the site's own host or CDN leaves an empty frame with no explanation. This endpoint makes both cases explainable. The fetch comes from PostHog's own network rather than from the screenshot renderer, so a host that varies its response by IP or user agent can answer this differently than it answers a screenshot render. Settled verdicts are cached briefly, so repeat checks for the same URL do not refetch it.
 * @summary Check whether a page can back a heatmap
 */
export const SavedPreflightCreateBody = /* @__PURE__ */ zod.object({
    url: zod
        .string()
        .describe(
            'Exact page URL to probe. Wildcards are not allowed. This is the URL that would be loaded in the live preview iframe, not the data URL used to look up heatmap events.'
        ),
})

/**
 * Speculatively render a screenshot for a page URL ahead of heatmap creation, so it's ready (or closer to ready) by the time the user reaches the generation screen. Renders a single preview width. Idempotent within a short window: returns the existing in-flight or completed prewarm render for the same URL and consent setting if one exists (200), otherwise starts a new one (201). The result is reused when a heatmap is later created for the same URL.
 */
export const savedPrewarmCreateBodyBlockConsentModalsDefault = false

export const SavedPrewarmCreateBody = /* @__PURE__ */ zod.object({
    url: zod
        .string()
        .describe('Exact page URL to speculatively render ahead of heatmap creation. Wildcards are not allowed.'),
    block_consent_modals: zod
        .boolean()
        .default(savedPrewarmCreateBodyBlockConsentModalsDefault)
        .describe(
            'When true, ask the headless browser to dismiss cookie\/consent banners before capturing. Must match the value used at creation time for the prewarmed render to be reused.'
        ),
})

/**
 * Loads an llms.txt file from a public URL for coverage analysis without saving it.
 * @summary Load an llms.txt file
 */
export const webAnalyticsFetchLlmsTxtBodyUrlMax = 2048

export const WebAnalyticsFetchLlmsTxtBody = /* @__PURE__ */ zod.object({
    url: zod
        .url()
        .max(webAnalyticsFetchLlmsTxtBodyUrlMax)
        .describe('Public HTTP or HTTPS URL of the llms.txt file to load.'),
})

/**
 * Clears a pending celebration for the given track and stage once the client has shown it, so it isn't celebrated again. Idempotent.
 * @summary Acknowledge an achievement celebration
 */
export const webAnalyticsAchievementsAcknowledgeCelebrationBodyStageMax = 5

export const WebAnalyticsAchievementsAcknowledgeCelebrationBody = /* @__PURE__ */ zod.object({
    track_key: zod.string().describe('Track of the celebration being acknowledged.'),
    stage: zod
        .number()
        .min(1)
        .max(webAnalyticsAchievementsAcknowledgeCelebrationBodyStageMax)
        .describe('Stage number being acknowledged, 1-5.'),
})

/**
 * Sets the requesting user's per-project Web analytics achievements preferences.
 * @summary Update Web analytics achievements preferences
 */
export const WebAnalyticsAchievementsUpdatePreferencesBody = /* @__PURE__ */ zod.object({
    achievements_opt_out: zod
        .boolean()
        .describe(
            'When true, the requesting user has hidden the Web analytics achievements gamification UI and suppressed achievement-unlocked notifications for this project. Scoped per (project, user).'
        ),
})

/**
 * Idempotently increments the requesting user's first-party counter for an in-product Web analytics interaction (slicing data, or opening a session recording), which drives the Explorer and Detective achievement tracks.
 * @summary Record a Web analytics interaction
 */
export const WebAnalyticsAchievementsRecordInteractionBody = /* @__PURE__ */ zod.object({
    interaction_kind: zod
        .enum(['data', 'recording'])
        .describe('\* `data` - data\n\* `recording` - recording')
        .describe(
            "Which interaction counter to increment: 'data' (slicing\/filtering the dashboard) or 'recording' (opening a session recording).\n\n\* `data` - data\n\* `recording` - recording"
        ),
})

export const webAnalyticsFilterPresetsCreateBodyNameMax = 400

export const WebAnalyticsFilterPresetsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(webAnalyticsFilterPresetsCreateBodyNameMax),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
})

export const webAnalyticsFilterPresetsUpdateBodyNameMax = 400

export const WebAnalyticsFilterPresetsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(webAnalyticsFilterPresetsUpdateBodyNameMax),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
})

export const webAnalyticsFilterPresetsPartialUpdateBodyNameMax = 400

export const WebAnalyticsFilterPresetsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(webAnalyticsFilterPresetsPartialUpdateBodyNameMax).optional(),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
})
