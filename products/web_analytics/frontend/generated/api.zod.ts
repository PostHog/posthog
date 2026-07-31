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
    AcknowledgeCelebrationRequestApi,
    HeatmapPrewarmRequestApi,
    PatchedSavedHeatmapRequestApi,
    PatchedWebAnalyticsFilterPresetApi,
    RecordInteractionRequestApi,
    SavedHeatmapRequestApi,
    WebAnalyticsFilterPresetApi,
    WebAnalyticsUserPreferencesApi,
} from './api.zod.schemas'

/**
 * Create a saved heatmap for a page URL. For type 'screenshot' (the default) this enqueues a headless render of the page at each target width; poll the saved heatmap or its content endpoint until status is 'completed'. Provide 'widths' to control which viewport widths are rendered.
 */
export const SavedCreateBody = SavedHeatmapRequestApi

/**
 * Update a saved heatmap (e.g. rename, change widths, or soft-delete via 'deleted'). Changing the URL of a 'screenshot' heatmap triggers a re-render.
 */
export const SavedPartialUpdateBody = PatchedSavedHeatmapRequestApi

/**
 * Speculatively render a screenshot for a page URL ahead of heatmap creation, so it's ready (or closer to ready) by the time the user reaches the generation screen. Renders a single preview width. Idempotent within a short window: returns the existing in-flight or completed prewarm render for the same URL and consent setting if one exists (200), otherwise starts a new one (201). The result is reused when a heatmap is later created for the same URL.
 */
export const SavedPrewarmCreateBody = HeatmapPrewarmRequestApi

/**
 * Clears a pending celebration for the given track and stage once the client has shown it, so it isn't celebrated again. Idempotent.
 * @summary Acknowledge an achievement celebration
 */
export const WebAnalyticsAchievementsAcknowledgeCelebrationBody = AcknowledgeCelebrationRequestApi

/**
 * Sets the requesting user's per-project Web analytics achievements preferences.
 * @summary Update Web analytics achievements preferences
 */
export const WebAnalyticsAchievementsUpdatePreferencesBody = WebAnalyticsUserPreferencesApi

/**
 * Idempotently increments the requesting user's first-party counter for an in-product Web analytics interaction (slicing data, or opening a session recording), which drives the Explorer and Detective achievement tracks.
 * @summary Record a Web analytics interaction
 */
export const WebAnalyticsAchievementsRecordInteractionBody = RecordInteractionRequestApi

export const WebAnalyticsFilterPresetsCreateBody = WebAnalyticsFilterPresetApi

export const WebAnalyticsFilterPresetsUpdateBody = WebAnalyticsFilterPresetApi

export const WebAnalyticsFilterPresetsPartialUpdateBody = PatchedWebAnalyticsFilterPresetApi
