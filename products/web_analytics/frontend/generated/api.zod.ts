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
