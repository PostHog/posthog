/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const HeatmapTypeApi = zod
    .enum(['screenshot', 'iframe', 'recording'])
    .describe('\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording')

export type HeatmapTypeApi = zod.input<typeof HeatmapTypeApi>
export type HeatmapTypeApiOutput = zod.output<typeof HeatmapTypeApi>

export const HeatmapScreenshotResponseStatusEnumApi = zod
    .enum(['processing', 'completed', 'failed'])
    .describe('\* `processing` - Processing\n\* `completed` - Completed\n\* `failed` - Failed')

export type HeatmapScreenshotResponseStatusEnumApi = zod.input<typeof HeatmapScreenshotResponseStatusEnumApi>
export type HeatmapScreenshotResponseStatusEnumApiOutput = zod.output<typeof HeatmapScreenshotResponseStatusEnumApi>

export const HeatmapSnapshotMetadataApi = zod.object({
    width: zod.number().describe('Viewport width (CSS pixels) this screenshot was rendered at.'),
    has_content: zod
        .boolean()
        .describe('Whether the rendered image for this width is ready to fetch from the content endpoint.'),
})

export type HeatmapSnapshotMetadataApi = zod.input<typeof HeatmapSnapshotMetadataApi>
export type HeatmapSnapshotMetadataApiOutput = zod.output<typeof HeatmapSnapshotMetadataApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const heatmapScreenshotResponseApiNameMax = 400

export const heatmapScreenshotResponseApiUrlMax = 2000

export const heatmapScreenshotResponseApiDataUrlMax = 2000

export const HeatmapScreenshotResponseApi = zod
    .object({
        id: zod.uuid(),
        short_id: zod.string().describe('Short, URL-safe identifier used as the lookup key for saved-heatmap routes.'),
        name: zod
            .string()
            .max(heatmapScreenshotResponseApiNameMax)
            .nullish()
            .describe('Human-readable label for the saved heatmap.'),
        url: zod
            .url()
            .max(heatmapScreenshotResponseApiUrlMax)
            .describe('The page URL this saved heatmap renders and overlays data on.'),
        data_url: zod
            .url()
            .max(heatmapScreenshotResponseApiDataUrlMax)
            .nullish()
            .describe("URL whose heatmap data is overlaid on the screenshot (defaults to 'url')."),
        target_widths: zod.unknown().optional().describe('Viewport widths (CSS pixels) the screenshot is rendered at.'),
        type: HeatmapTypeApi.optional().describe(
            "Render mode: 'screenshot', 'iframe', or 'recording'.\n\n\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording"
        ),
        status: HeatmapScreenshotResponseStatusEnumApi.describe(
            "Screenshot generation status: 'processing', 'completed', or 'failed'.\n\n\* `processing` - Processing\n\* `completed` - Completed\n\* `failed` - Failed"
        ),
        has_content: zod.boolean().describe('Whether at least one rendered image is ready to fetch.'),
        snapshots: zod
            .array(HeatmapSnapshotMetadataApi)
            .describe('Per-width render metadata. Fetch the actual image bytes for a width from the content endpoint.'),
        deleted: zod.boolean().optional().describe('Soft-delete flag; deleted heatmaps are hidden from the list.'),
        block_consent_modals: zod
            .boolean()
            .optional()
            .describe(
                "Whether the headless browser dismisses cookie\/consent banners before capturing the screenshot. Only applies to 'screenshot' heatmaps."
            ),
        created_by: UserBasicApi,
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        exception: zod.string().nullable().describe('Error detail when screenshot generation failed, otherwise null.'),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type HeatmapScreenshotResponseApi = zod.input<typeof HeatmapScreenshotResponseApi>
export type HeatmapScreenshotResponseApiOutput = zod.output<typeof HeatmapScreenshotResponseApi>

export const HeatmapResponseItemApi = zod.object({
    count: zod.number(),
    pointer_y: zod.number(),
    pointer_relative_x: zod.number(),
    pointer_target_fixed: zod.boolean(),
})

export type HeatmapResponseItemApi = zod.input<typeof HeatmapResponseItemApi>
export type HeatmapResponseItemApiOutput = zod.output<typeof HeatmapResponseItemApi>

export const HeatmapFoldSummaryApi = zod.object({
    total_count: zod
        .number()
        .describe(
            "Number of non-fixed interactions of this type on the page in the window (the population the above\/below-the-fold split applies to; fixed-position elements are excluded since they're always on screen)."
        ),
    below_fold_count: zod
        .number()
        .describe(
            "How many of those interactions happened below the user's initial viewport — i.e. they had to scroll to reach them."
        ),
    pct_below_fold: zod
        .number()
        .describe(
            'Percentage of non-fixed interactions that were below the initial viewport (0-100). A high value means engaged content sits off the first screen and is a candidate to move up.'
        ),
    median_viewport_height: zod
        .number()
        .nullable()
        .describe(
            'Median viewport height in CSS pixels across the matched interactions — the typical fold line to recommend against. Null when there are no interactions.'
        ),
})

export type HeatmapFoldSummaryApi = zod.input<typeof HeatmapFoldSummaryApi>
export type HeatmapFoldSummaryApiOutput = zod.output<typeof HeatmapFoldSummaryApi>

export const heatmapsResponseApiHasMoreDefault = false

export const HeatmapsResponseApi = zod.object({
    results: zod.array(HeatmapResponseItemApi),
    fold: zod
        .union([HeatmapFoldSummaryApi, zod.null()])
        .optional()
        .describe(
            'Above\/below-the-fold summary for the returned interactions. Present for click\/rageclick\/mousemove; omitted for scrolldepth.'
        ),
    has_more: zod
        .boolean()
        .default(heatmapsResponseApiHasMoreDefault)
        .describe(
            "True when more coordinate points exist beyond the returned page. Raise 'limit' or page with 'offset' to fetch them. Always false for scrolldepth, which returns every bucket."
        ),
})

export type HeatmapsResponseApi = zod.input<typeof HeatmapsResponseApi>
export type HeatmapsResponseApiOutput = zod.output<typeof HeatmapsResponseApi>

export const HeatmapEventItemApi = zod.object({
    session_id: zod.string().nullish(),
    distinct_id: zod.string(),
    timestamp: zod.iso.datetime({ offset: true }),
    pointer_relative_x: zod.number(),
    pointer_y: zod.number(),
    current_url: zod.string(),
    type: zod.string(),
})

export type HeatmapEventItemApi = zod.input<typeof HeatmapEventItemApi>
export type HeatmapEventItemApiOutput = zod.output<typeof HeatmapEventItemApi>

export const HeatmapEventsResponseApi = zod.object({
    results: zod.array(HeatmapEventItemApi),
    total_count: zod.number(),
    has_more: zod.boolean(),
})

export type HeatmapEventsResponseApi = zod.input<typeof HeatmapEventsResponseApi>
export type HeatmapEventsResponseApiOutput = zod.output<typeof HeatmapEventsResponseApi>

export const SavedHeatmapListResponseApi = zod.object({
    results: zod.array(HeatmapScreenshotResponseApi),
    count: zod.number().describe('Total number of saved heatmaps matching the filters.'),
})

export type SavedHeatmapListResponseApi = zod.input<typeof SavedHeatmapListResponseApi>
export type SavedHeatmapListResponseApiOutput = zod.output<typeof SavedHeatmapListResponseApi>

export const savedHeatmapRequestApiNameMax = 400

export const savedHeatmapRequestApiUrlMax = 2000

export const savedHeatmapRequestApiDataUrlMax = 2000

export const savedHeatmapRequestApiWidthsItemMin = 100
export const savedHeatmapRequestApiWidthsItemMax = 3000

export const savedHeatmapRequestApiWidthsMax = 16

export const savedHeatmapRequestApiTypeDefault = `screenshot`

export const SavedHeatmapRequestApi = zod.object({
    name: zod
        .string()
        .max(savedHeatmapRequestApiNameMax)
        .nullish()
        .describe('Human-readable label for the saved heatmap.'),
    url: zod
        .url()
        .max(savedHeatmapRequestApiUrlMax)
        .describe('Exact page URL to render and overlay heatmap data on. Wildcards are not allowed.'),
    data_url: zod
        .url()
        .max(savedHeatmapRequestApiDataUrlMax)
        .nullish()
        .describe("URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted."),
    widths: zod
        .array(zod.number().min(savedHeatmapRequestApiWidthsItemMin).max(savedHeatmapRequestApiWidthsItemMax))
        .max(savedHeatmapRequestApiWidthsMax)
        .optional()
        .describe(
            'Viewport widths (px, 100-3000) to render the heatmap screenshot at — one render per width. Defaults to [320, 375, 425, 768, 1024, 1440, 1920] when omitted. At most 16 widths.'
        ),
    type: HeatmapTypeApi.default(savedHeatmapRequestApiTypeDefault).describe(
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

export type SavedHeatmapRequestApi = zod.input<typeof SavedHeatmapRequestApi>
export type SavedHeatmapRequestApiOutput = zod.output<typeof SavedHeatmapRequestApi>

export const patchedSavedHeatmapRequestApiNameMax = 400

export const patchedSavedHeatmapRequestApiUrlMax = 2000

export const patchedSavedHeatmapRequestApiDataUrlMax = 2000

export const patchedSavedHeatmapRequestApiWidthsItemMin = 100
export const patchedSavedHeatmapRequestApiWidthsItemMax = 3000

export const patchedSavedHeatmapRequestApiWidthsMax = 16

export const patchedSavedHeatmapRequestApiTypeDefault = `screenshot`

export const PatchedSavedHeatmapRequestApi = zod.object({
    name: zod
        .string()
        .max(patchedSavedHeatmapRequestApiNameMax)
        .nullish()
        .describe('Human-readable label for the saved heatmap.'),
    url: zod
        .url()
        .max(patchedSavedHeatmapRequestApiUrlMax)
        .optional()
        .describe('Exact page URL to render and overlay heatmap data on. Wildcards are not allowed.'),
    data_url: zod
        .url()
        .max(patchedSavedHeatmapRequestApiDataUrlMax)
        .nullish()
        .describe("URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted."),
    widths: zod
        .array(
            zod.number().min(patchedSavedHeatmapRequestApiWidthsItemMin).max(patchedSavedHeatmapRequestApiWidthsItemMax)
        )
        .max(patchedSavedHeatmapRequestApiWidthsMax)
        .optional()
        .describe(
            'Viewport widths (px, 100-3000) to render the heatmap screenshot at — one render per width. Defaults to [320, 375, 425, 768, 1024, 1440, 1920] when omitted. At most 16 widths.'
        ),
    type: HeatmapTypeApi.default(patchedSavedHeatmapRequestApiTypeDefault).describe(
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

export type PatchedSavedHeatmapRequestApi = zod.input<typeof PatchedSavedHeatmapRequestApi>
export type PatchedSavedHeatmapRequestApiOutput = zod.output<typeof PatchedSavedHeatmapRequestApi>

export const heatmapPrewarmRequestApiBlockConsentModalsDefault = false

export const HeatmapPrewarmRequestApi = zod.object({
    url: zod
        .string()
        .describe('Exact page URL to speculatively render ahead of heatmap creation. Wildcards are not allowed.'),
    block_consent_modals: zod
        .boolean()
        .default(heatmapPrewarmRequestApiBlockConsentModalsDefault)
        .describe(
            'When true, ask the headless browser to dismiss cookie\/consent banners before capturing. Must match the value used at creation time for the prewarmed render to be reused.'
        ),
})

export type HeatmapPrewarmRequestApi = zod.input<typeof HeatmapPrewarmRequestApi>
export type HeatmapPrewarmRequestApiOutput = zod.output<typeof HeatmapPrewarmRequestApi>

export const WoWChangeDirectionEnumApi = zod.enum(['Up', 'Down']).describe('\* `Up` - Up\n\* `Down` - Down')

export type WoWChangeDirectionEnumApi = zod.input<typeof WoWChangeDirectionEnumApi>
export type WoWChangeDirectionEnumApiOutput = zod.output<typeof WoWChangeDirectionEnumApi>

export const WoWChangeApi = zod.object({
    percent: zod.number().describe('Absolute percentage change, rounded to nearest integer.'),
    direction: WoWChangeDirectionEnumApi.describe(
        'Direction of the change relative to the prior period.\n\n\* `Up` - Up\n\* `Down` - Down'
    ),
    color: zod.string().describe('Hex color indicating whether the change is a positive or negative signal.'),
    text: zod.string().describe("Short label, e.g. 'Up 12%'."),
    long_text: zod.string().describe("Verbose label, e.g. 'Up 12% from prior period'."),
})

export type WoWChangeApi = zod.input<typeof WoWChangeApi>
export type WoWChangeApiOutput = zod.output<typeof WoWChangeApi>

export const NumericMetricApi = zod.object({
    current: zod.number().describe('Value for the most recent period.'),
    previous: zod.number().nullable().describe('Value for the prior period, if available.'),
    change: zod.union([WoWChangeApi, zod.null()]).describe('Period-over-period change, null when not meaningful.'),
})

export type NumericMetricApi = zod.input<typeof NumericMetricApi>
export type NumericMetricApiOutput = zod.output<typeof NumericMetricApi>

export const DurationMetricApi = zod.object({
    current: zod.string().describe("Human-readable duration, e.g. '2m 34s'."),
    previous: zod.string().nullable().describe("Prior-period duration, e.g. '2m 10s'."),
    change: zod.union([WoWChangeApi, zod.null()]).describe('Period-over-period change, null when not meaningful.'),
})

export type DurationMetricApi = zod.input<typeof DurationMetricApi>
export type DurationMetricApiOutput = zod.output<typeof DurationMetricApi>

export const TopPageApi = zod.object({
    host: zod.string().describe('Host for the page, if recorded.'),
    path: zod.string().describe('URL path.'),
    visitors: zod.number().describe('Unique visitors in the period.'),
    change: zod
        .union([WoWChangeApi, zod.null()])
        .describe('Period-over-period change in visitors, null when not meaningful.'),
})

export type TopPageApi = zod.input<typeof TopPageApi>
export type TopPageApiOutput = zod.output<typeof TopPageApi>

export const TopSourceApi = zod.object({
    name: zod.string().describe('Initial referring domain.'),
    visitors: zod.number().describe('Unique visitors from this source.'),
    change: zod
        .union([WoWChangeApi, zod.null()])
        .describe('Period-over-period change in visitors, null when not meaningful.'),
})

export type TopSourceApi = zod.input<typeof TopSourceApi>
export type TopSourceApiOutput = zod.output<typeof TopSourceApi>

export const GoalApi = zod.object({
    name: zod.string().describe('Goal name (action name).'),
    conversions: zod.number().describe('Total conversions in the period.'),
    change: zod
        .union([WoWChangeApi, zod.null()])
        .describe('Period-over-period change in conversions, null when not meaningful.'),
})

export type GoalApi = zod.input<typeof GoalApi>
export type GoalApiOutput = zod.output<typeof GoalApi>

export const RecapPersonaApi = zod.object({
    id: zod
        .string()
        .describe(
            'Stable persona identifier. One of: just_getting_started, conversion_machine, traffic_magnet, crowd_favorite, search_hog, word_of_mouth, loyal_following, rising_star, steady_hog.'
        ),
    name: zod.string().describe("Display name for the persona, e.g. 'Traffic Magnet'."),
    emoji: zod.string().describe('Emoji representing the persona.'),
    blurb: zod.string().describe('One-line explanation of why this persona was assigned this week.'),
    color: zod.string().describe('Hex accent color for rendering the persona card.'),
})

export type RecapPersonaApi = zod.input<typeof RecapPersonaApi>
export type RecapPersonaApiOutput = zod.output<typeof RecapPersonaApi>

export const RecapHighlightApi = zod.object({
    id: zod.string().describe("Stable highlight identifier, e.g. 'milestone', 'rising_page', 'top_source'."),
    emoji: zod.string().describe('Emoji for the highlight.'),
    title: zod.string().describe("Short headline for the highlight, e.g. 'Rising star page'."),
    value: zod.string().describe('The standout value, e.g. a page path or visitor count.'),
    detail: zod.string().describe('Supporting sentence for the highlight.'),
})

export type RecapHighlightApi = zod.input<typeof RecapHighlightApi>
export type RecapHighlightApiOutput = zod.output<typeof RecapHighlightApi>

export const WebAnalyticsRecapResponseApi = zod.object({
    visitors: NumericMetricApi.describe('Unique visitors.'),
    pageviews: NumericMetricApi.describe('Total pageviews.'),
    sessions: NumericMetricApi.describe('Total sessions.'),
    bounce_rate: NumericMetricApi.describe('Bounce rate (0–100).'),
    avg_session_duration: DurationMetricApi.describe('Average session duration.'),
    top_pages: zod.array(TopPageApi).describe('Top 5 pages by unique visitors.'),
    top_sources: zod.array(TopSourceApi).describe('Top 5 traffic sources by unique visitors.'),
    goals: zod.array(GoalApi).describe('Goal conversions.'),
    dashboard_url: zod.url().describe('Link to the Web analytics dashboard for this project.'),
    persona: RecapPersonaApi.describe("The single weekly persona assigned from this week's data."),
    highlights: zod.array(RecapHighlightApi).describe('Up to three screenshot-worthy superlatives for the week.'),
    period_label: zod.string().describe("Human-readable period label, e.g. 'Last 7 days'."),
    period_start: zod.iso.date().describe('First date included in the recap period, in the project timezone.'),
    period_end: zod.iso.date().describe('Final date included in the recap period, in the project timezone.'),
    project_name: zod.string().describe('Name of the project this recap is for.'),
    recap_url: zod.url().describe("Canonical link to this project's weekly recap."),
})

export type WebAnalyticsRecapResponseApi = zod.input<typeof WebAnalyticsRecapResponseApi>
export type WebAnalyticsRecapResponseApiOutput = zod.output<typeof WebAnalyticsRecapResponseApi>

export const WeeklyDigestResponseApi = zod.object({
    visitors: NumericMetricApi.describe('Unique visitors.'),
    pageviews: NumericMetricApi.describe('Total pageviews.'),
    sessions: NumericMetricApi.describe('Total sessions.'),
    bounce_rate: NumericMetricApi.describe('Bounce rate (0–100).'),
    avg_session_duration: DurationMetricApi.describe('Average session duration.'),
    top_pages: zod.array(TopPageApi).describe('Top 5 pages by unique visitors.'),
    top_sources: zod.array(TopSourceApi).describe('Top 5 traffic sources by unique visitors.'),
    goals: zod.array(GoalApi).describe('Goal conversions.'),
    dashboard_url: zod.url().describe('Link to the Web analytics dashboard for this project.'),
})

export type WeeklyDigestResponseApi = zod.input<typeof WeeklyDigestResponseApi>
export type WeeklyDigestResponseApiOutput = zod.output<typeof WeeklyDigestResponseApi>

export const acknowledgeCelebrationRequestApiStageMax = 5

export const AcknowledgeCelebrationRequestApi = zod.object({
    track_key: zod.string().describe('Track of the celebration being acknowledged.'),
    stage: zod
        .number()
        .min(1)
        .max(acknowledgeCelebrationRequestApiStageMax)
        .describe('Stage number being acknowledged, 1-5.'),
})

export type AcknowledgeCelebrationRequestApi = zod.input<typeof AcknowledgeCelebrationRequestApi>
export type AcknowledgeCelebrationRequestApiOutput = zod.output<typeof AcknowledgeCelebrationRequestApi>

export const AcknowledgeCelebrationResponseApi = zod.object({
    acknowledged: zod.boolean().describe('True if a matching pending celebration was cleared (idempotent).'),
})

export type AcknowledgeCelebrationResponseApi = zod.input<typeof AcknowledgeCelebrationResponseApi>
export type AcknowledgeCelebrationResponseApiOutput = zod.output<typeof AcknowledgeCelebrationResponseApi>

export const AchievementDefinitionScopeEnumApi = zod
    .enum(['user', 'team'])
    .describe('\* `user` - user\n\* `team` - team')

export type AchievementDefinitionScopeEnumApi = zod.input<typeof AchievementDefinitionScopeEnumApi>
export type AchievementDefinitionScopeEnumApiOutput = zod.output<typeof AchievementDefinitionScopeEnumApi>

export const AchievementStageApi = zod.object({
    stage: zod.number().describe('Stage number within the track, 1-5.'),
    name: zod.string().describe("Stage name within the track, e.g. 'On a roll'."),
    threshold: zod.number().describe("Progress value needed to unlock this stage, resolved for the user's streak arm."),
})

export type AchievementStageApi = zod.input<typeof AchievementStageApi>
export type AchievementStageApiOutput = zod.output<typeof AchievementStageApi>

export const AchievementDefinitionApi = zod.object({
    key: zod.string().describe("Stable track identifier, e.g. 'streak'."),
    display_name: zod.string().describe('Human-readable track name.'),
    description: zod.string().describe('One-line description of what the track rewards.'),
    scope: AchievementDefinitionScopeEnumApi.describe(
        'Whether the track is tracked per user or per team.\n\n\* `user` - user\n\* `team` - team'
    ),
    is_experiment_track: zod
        .boolean()
        .describe('True for the streak track, whose thresholds vary by the streak-cadence experiment arm.'),
    stages: zod.array(AchievementStageApi).describe('The five stages of this track, in ascending threshold order.'),
})

export type AchievementDefinitionApi = zod.input<typeof AchievementDefinitionApi>
export type AchievementDefinitionApiOutput = zod.output<typeof AchievementDefinitionApi>

export const AchievementProgressApi = zod.object({
    track_key: zod.string().describe('Track this progress row belongs to.'),
    current_stage: zod.number().describe('Highest stage unlocked so far, 0-5.'),
    progress_value: zod.number().describe('Most recently computed progress value for the track.'),
    last_computed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the track was last recomputed, or null if it never has been.'),
    unlocked_at: zod
        .record(zod.string(), zod.iso.datetime({ offset: true }))
        .describe("Map of unlocked stage number (as a string, '1'-'5') to the ISO timestamp it was unlocked."),
})

export type AchievementProgressApi = zod.input<typeof AchievementProgressApi>
export type AchievementProgressApiOutput = zod.output<typeof AchievementProgressApi>

export const PendingCelebrationApi = zod.object({
    track_key: zod.string().describe('Track whose stage was newly unlocked.'),
    stage: zod.number().describe('Newly unlocked stage number, 1-5.'),
    stage_name: zod.string().describe('Name of the unlocked stage, shown in the celebration UI.'),
})

export type PendingCelebrationApi = zod.input<typeof PendingCelebrationApi>
export type PendingCelebrationApiOutput = zod.output<typeof PendingCelebrationApi>

export const AchievementsListResponseApi = zod.object({
    definitions: zod
        .array(AchievementDefinitionApi)
        .describe("All Wave-1 track definitions, thresholds resolved for the user's streak arm."),
    user_progress: zod.array(AchievementProgressApi).describe("The requesting user's progress on per-user tracks."),
    team_progress: zod.array(AchievementProgressApi).describe("The team's progress on per-team tracks."),
    pending_celebrations: zod
        .array(PendingCelebrationApi)
        .describe('Newly unlocked stages awaiting an in-session celebration; acknowledge each to clear it.'),
})

export type AchievementsListResponseApi = zod.input<typeof AchievementsListResponseApi>
export type AchievementsListResponseApiOutput = zod.output<typeof AchievementsListResponseApi>

export const WebAnalyticsUserPreferencesApi = zod.object({
    achievements_opt_out: zod
        .boolean()
        .describe(
            'When true, the requesting user has hidden the Web analytics achievements gamification UI and suppressed achievement-unlocked notifications for this project. Scoped per (project, user).'
        ),
})

export type WebAnalyticsUserPreferencesApi = zod.input<typeof WebAnalyticsUserPreferencesApi>
export type WebAnalyticsUserPreferencesApiOutput = zod.output<typeof WebAnalyticsUserPreferencesApi>

export const InteractionKindEnumApi = zod
    .enum(['data', 'recording'])
    .describe('\* `data` - data\n\* `recording` - recording')

export type InteractionKindEnumApi = zod.input<typeof InteractionKindEnumApi>
export type InteractionKindEnumApiOutput = zod.output<typeof InteractionKindEnumApi>

export const RecordInteractionRequestApi = zod.object({
    interaction_kind: InteractionKindEnumApi.describe(
        "Which interaction counter to increment: 'data' (slicing\/filtering the dashboard) or 'recording' (opening a session recording).\n\n\* `data` - data\n\* `recording` - recording"
    ),
})

export type RecordInteractionRequestApi = zod.input<typeof RecordInteractionRequestApi>
export type RecordInteractionRequestApiOutput = zod.output<typeof RecordInteractionRequestApi>

export const RecordInteractionResponseApi = zod.object({
    recorded: zod.boolean().describe('True once the interaction has been counted for the user.'),
})

export type RecordInteractionResponseApi = zod.input<typeof RecordInteractionResponseApi>
export type RecordInteractionResponseApiOutput = zod.output<typeof RecordInteractionResponseApi>

export const RecordVisitResponseApi = zod.object({
    recorded: zod.boolean().describe("True once today's visit row exists for the user."),
})

export type RecordVisitResponseApi = zod.input<typeof RecordVisitResponseApi>
export type RecordVisitResponseApiOutput = zod.output<typeof RecordVisitResponseApi>

export const webAnalyticsFilterPresetApiNameMax = 400

export const WebAnalyticsFilterPresetApi = zod.object({
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string().max(webAnalyticsFilterPresetApiNameMax),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
    last_modified_at: zod.iso.datetime({ offset: true }),
    last_modified_by: UserBasicApi,
})

export type WebAnalyticsFilterPresetApi = zod.input<typeof WebAnalyticsFilterPresetApi>
export type WebAnalyticsFilterPresetApiOutput = zod.output<typeof WebAnalyticsFilterPresetApi>

export const PaginatedWebAnalyticsFilterPresetListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(WebAnalyticsFilterPresetApi),
})

export type PaginatedWebAnalyticsFilterPresetListApi = zod.input<typeof PaginatedWebAnalyticsFilterPresetListApi>
export type PaginatedWebAnalyticsFilterPresetListApiOutput = zod.output<typeof PaginatedWebAnalyticsFilterPresetListApi>

export const patchedWebAnalyticsFilterPresetApiNameMax = 400

export const PatchedWebAnalyticsFilterPresetApi = zod.object({
    id: zod.uuid().optional(),
    short_id: zod.string().optional(),
    name: zod.string().max(patchedWebAnalyticsFilterPresetApiNameMax).optional(),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
    last_modified_at: zod.iso.datetime({ offset: true }).optional(),
    last_modified_by: UserBasicApi.optional(),
})

export type PatchedWebAnalyticsFilterPresetApi = zod.input<typeof PatchedWebAnalyticsFilterPresetApi>
export type PatchedWebAnalyticsFilterPresetApiOutput = zod.output<typeof PatchedWebAnalyticsFilterPresetApi>
