import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    AchievementsListResponseApi,
    AcknowledgeCelebrationRequestApi,
    AcknowledgeCelebrationResponseApi,
    HeatmapEventsResponseApi,
    HeatmapScreenshotResponseApi,
    HeatmapScreenshotsContentRetrieveParams,
    HeatmapsEventsRetrieveParams,
    HeatmapsListParams,
    HeatmapsResponseApi,
    PaginatedWebAnalyticsFilterPresetListApi,
    PatchedSavedHeatmapRequestApi,
    PatchedWebAnalyticsFilterPresetApi,
    RecordInteractionRequestApi,
    RecordInteractionResponseApi,
    RecordVisitResponseApi,
    SavedHeatmapListResponseApi,
    SavedHeatmapRequestApi,
    SavedListParams,
    WebAnalyticsFilterPresetApi,
    WebAnalyticsFilterPresetsListParams,
    WebAnalyticsRecapParams,
    WebAnalyticsRecapResponseApi,
    WebAnalyticsUserPreferencesApi,
    WebAnalyticsWeeklyDigestParams,
    WeeklyDigestResponseApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getHeatmapScreenshotsContentRetrieveUrl = (
    projectId: string,
    id: string,
    params?: HeatmapScreenshotsContentRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/heatmap_screenshots/${id}/content/?${stringifiedParams}`
        : `/api/projects/${projectId}/heatmap_screenshots/${id}/content/`
}

/**
 * Fetch the rendered screenshot image (JPEG bytes) for a saved heatmap at a given viewport width. Returns 202 with the saved-heatmap metadata while the screenshot is still being generated.
 */
export const heatmapScreenshotsContentRetrieve = async (
    projectId: string,
    id: string,
    params?: HeatmapScreenshotsContentRetrieveParams,
    options?: RequestInit
): Promise<Blob | HeatmapScreenshotResponseApi> => {
    return apiMutator<Blob | HeatmapScreenshotResponseApi>(
        getHeatmapScreenshotsContentRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getHeatmapsListUrl = (projectId: string, params?: HeatmapsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/heatmaps/?${stringifiedParams}`
        : `/api/projects/${projectId}/heatmaps/`
}

/**
 * Aggregated heatmap interactions for a page. For type 'click'/'rageclick'/'mousemove' each result is a point with relative x, absolute client-y, and a count. For type 'scrolldepth' the response is scroll-depth buckets instead (cumulative reach down the page).
 */
export const heatmapsList = async (
    projectId: string,
    params?: HeatmapsListParams,
    options?: RequestInit
): Promise<HeatmapsResponseApi[]> => {
    return apiMutator<HeatmapsResponseApi[]>(getHeatmapsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getHeatmapsEventsRetrieveUrl = (projectId: string, params: HeatmapsEventsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/heatmaps/events/?${stringifiedParams}`
        : `/api/projects/${projectId}/heatmaps/events/`
}

/**
 * Drill into the individual session interactions behind one or more heatmap coordinates. Pass the 'points' you want to inspect (from the heatmaps list response) to get the underlying per-session events, so you can jump to the session recordings that produced a hotspot.
 */
export const heatmapsEventsRetrieve = async (
    projectId: string,
    params: HeatmapsEventsRetrieveParams,
    options?: RequestInit
): Promise<HeatmapEventsResponseApi> => {
    return apiMutator<HeatmapEventsResponseApi>(getHeatmapsEventsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSavedListUrl = (projectId: string, params?: SavedListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/saved/?${stringifiedParams}`
        : `/api/projects/${projectId}/saved/`
}

/**
 * List saved heatmaps for the project. A saved heatmap pins a page URL and a set of viewport widths, and (for type 'screenshot') renders the page so heatmap data can be overlaid on it.
 */
export const savedList = async (
    projectId: string,
    params?: SavedListParams,
    options?: RequestInit
): Promise<SavedHeatmapListResponseApi[]> => {
    return apiMutator<SavedHeatmapListResponseApi[]>(getSavedListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSavedCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/saved/`
}

/**
 * Create a saved heatmap for a page URL. For type 'screenshot' (the default) this enqueues a headless render of the page at each target width; poll the saved heatmap or its content endpoint until status is 'completed'. Provide 'widths' to control which viewport widths are rendered.
 */
export const savedCreate = async (
    projectId: string,
    savedHeatmapRequestApi: SavedHeatmapRequestApi,
    options?: RequestInit
): Promise<HeatmapScreenshotResponseApi> => {
    return apiMutator<HeatmapScreenshotResponseApi>(getSavedCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(savedHeatmapRequestApi),
    })
}

export const getSavedRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/saved/${shortId}/`
}

/**
 * Get a single saved heatmap by its short_id, including per-width render status.
 */
export const savedRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<HeatmapScreenshotResponseApi> => {
    return apiMutator<HeatmapScreenshotResponseApi>(getSavedRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getSavedPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/saved/${shortId}/`
}

/**
 * Update a saved heatmap (e.g. rename, change widths, or soft-delete via 'deleted'). Changing the URL of a 'screenshot' heatmap triggers a re-render.
 */
export const savedPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedSavedHeatmapRequestApi?: PatchedSavedHeatmapRequestApi,
    options?: RequestInit
): Promise<HeatmapScreenshotResponseApi> => {
    return apiMutator<HeatmapScreenshotResponseApi>(getSavedPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSavedHeatmapRequestApi),
    })
}

export const getSavedDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/saved/${shortId}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const savedDestroy = async (projectId: string, shortId: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getSavedDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getSavedRegenerateCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/saved/${shortId}/regenerate/`
}

/**
 * Re-run screenshot generation for a saved heatmap of type 'screenshot'. Clears existing renders and re-renders at every target width; status returns to 'processing'.
 */
export const savedRegenerateCreate = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<HeatmapScreenshotResponseApi> => {
    return apiMutator<HeatmapScreenshotResponseApi>(getSavedRegenerateCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
    })
}

export const getWebAnalyticsRecapUrl = (projectId: string, params?: WebAnalyticsRecapParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/web_analytics/recap/?${stringifiedParams}`
        : `/api/projects/${projectId}/web_analytics/recap/`
}

/**
 * The 'Wrapped'-style weekly recap: everything in the weekly digest (visitors, pageviews, sessions, bounce rate, average session duration with period-over-period comparisons, top pages, top sources, and goals) plus a single derived weekly persona and a short list of screenshot-worthy highlights for the period.
 * @summary Weekly web analytics recap
 */
export const webAnalyticsRecap = async (
    projectId: string,
    params?: WebAnalyticsRecapParams,
    options?: RequestInit
): Promise<WebAnalyticsRecapResponseApi> => {
    return apiMutator<WebAnalyticsRecapResponseApi>(getWebAnalyticsRecapUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getWebAnalyticsWeeklyDigestUrl = (projectId: string, params?: WebAnalyticsWeeklyDigestParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/web_analytics/weekly_digest/?${stringifiedParams}`
        : `/api/projects/${projectId}/web_analytics/weekly_digest/`
}

/**
 * Summarizes a project's web analytics over a lookback window (default 7 days): unique visitors, pageviews, sessions, bounce rate, and average session duration with period-over-period comparisons, plus the top 5 pages, top 5 traffic sources, and goal conversions.
 * @summary Summarize web analytics
 */
export const webAnalyticsWeeklyDigest = async (
    projectId: string,
    params?: WebAnalyticsWeeklyDigestParams,
    options?: RequestInit
): Promise<WeeklyDigestResponseApi> => {
    return apiMutator<WeeklyDigestResponseApi>(getWebAnalyticsWeeklyDigestUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getWebAnalyticsAchievementsAcknowledgeCelebrationUrl = (projectId: string) => {
    return `/api/projects/${projectId}/web_analytics_achievements/acknowledge_celebration/`
}

/**
 * Clears a pending celebration for the given track and stage once the client has shown it, so it isn't celebrated again. Idempotent.
 * @summary Acknowledge an achievement celebration
 */
export const webAnalyticsAchievementsAcknowledgeCelebration = async (
    projectId: string,
    acknowledgeCelebrationRequestApi: AcknowledgeCelebrationRequestApi,
    options?: RequestInit
): Promise<AcknowledgeCelebrationResponseApi> => {
    return apiMutator<AcknowledgeCelebrationResponseApi>(
        getWebAnalyticsAchievementsAcknowledgeCelebrationUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(acknowledgeCelebrationRequestApi),
        }
    )
}

export const getWebAnalyticsAchievementsOverviewUrl = (projectId: string) => {
    return `/api/projects/${projectId}/web_analytics_achievements/overview/`
}

/**
 * Returns the achievement track definitions (thresholds resolved for the requesting user's streak-cadence arm), the user's and team's progress, and any newly unlocked stages awaiting an in-session celebration.
 * @summary Get Web analytics achievements overview
 */
export const webAnalyticsAchievementsOverview = async (
    projectId: string,
    options?: RequestInit
): Promise<AchievementsListResponseApi> => {
    return apiMutator<AchievementsListResponseApi>(getWebAnalyticsAchievementsOverviewUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getWebAnalyticsAchievementsPreferencesUrl = (projectId: string) => {
    return `/api/projects/${projectId}/web_analytics_achievements/preferences/`
}

/**
 * Returns the requesting user's per-project Web analytics achievements preferences.
 * @summary Get Web analytics achievements preferences
 */
export const webAnalyticsAchievementsPreferences = async (
    projectId: string,
    options?: RequestInit
): Promise<WebAnalyticsUserPreferencesApi> => {
    return apiMutator<WebAnalyticsUserPreferencesApi>(getWebAnalyticsAchievementsPreferencesUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getWebAnalyticsAchievementsUpdatePreferencesUrl = (projectId: string) => {
    return `/api/projects/${projectId}/web_analytics_achievements/preferences/`
}

/**
 * Sets the requesting user's per-project Web analytics achievements preferences.
 * @summary Update Web analytics achievements preferences
 */
export const webAnalyticsAchievementsUpdatePreferences = async (
    projectId: string,
    webAnalyticsUserPreferencesApi: WebAnalyticsUserPreferencesApi,
    options?: RequestInit
): Promise<WebAnalyticsUserPreferencesApi> => {
    return apiMutator<WebAnalyticsUserPreferencesApi>(getWebAnalyticsAchievementsUpdatePreferencesUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(webAnalyticsUserPreferencesApi),
    })
}

export const getWebAnalyticsAchievementsRecordInteractionUrl = (projectId: string) => {
    return `/api/projects/${projectId}/web_analytics_achievements/record_interaction/`
}

/**
 * Idempotently increments the requesting user's first-party counter for an in-product Web analytics interaction (slicing data, or opening a session recording), which drives the Explorer and Detective achievement tracks.
 * @summary Record a Web analytics interaction
 */
export const webAnalyticsAchievementsRecordInteraction = async (
    projectId: string,
    recordInteractionRequestApi: RecordInteractionRequestApi,
    options?: RequestInit
): Promise<RecordInteractionResponseApi> => {
    return apiMutator<RecordInteractionResponseApi>(getWebAnalyticsAchievementsRecordInteractionUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(recordInteractionRequestApi),
    })
}

export const getWebAnalyticsAchievementsRecordVisitUrl = (projectId: string) => {
    return `/api/projects/${projectId}/web_analytics_achievements/record_visit/`
}

/**
 * Idempotently records that the requesting user opened Web analytics today (team-local date) and schedules a debounced achievement recompute. Intended to be called once per session.
 * @summary Record a Web analytics visit
 */
export const webAnalyticsAchievementsRecordVisit = async (
    projectId: string,
    options?: RequestInit
): Promise<RecordVisitResponseApi> => {
    return apiMutator<RecordVisitResponseApi>(getWebAnalyticsAchievementsRecordVisitUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getWebAnalyticsFilterPresetsListUrl = (
    projectId: string,
    params?: WebAnalyticsFilterPresetsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/web_analytics_filter_presets/?${stringifiedParams}`
        : `/api/projects/${projectId}/web_analytics_filter_presets/`
}

export const webAnalyticsFilterPresetsList = async (
    projectId: string,
    params?: WebAnalyticsFilterPresetsListParams,
    options?: RequestInit
): Promise<PaginatedWebAnalyticsFilterPresetListApi> => {
    return apiMutator<PaginatedWebAnalyticsFilterPresetListApi>(
        getWebAnalyticsFilterPresetsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWebAnalyticsFilterPresetsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/web_analytics_filter_presets/`
}

export const webAnalyticsFilterPresetsCreate = async (
    projectId: string,
    webAnalyticsFilterPresetApi: NonReadonly<WebAnalyticsFilterPresetApi>,
    options?: RequestInit
): Promise<WebAnalyticsFilterPresetApi> => {
    return apiMutator<WebAnalyticsFilterPresetApi>(getWebAnalyticsFilterPresetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(webAnalyticsFilterPresetApi),
    })
}

export const getWebAnalyticsFilterPresetsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/web_analytics_filter_presets/${shortId}/`
}

export const webAnalyticsFilterPresetsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<WebAnalyticsFilterPresetApi> => {
    return apiMutator<WebAnalyticsFilterPresetApi>(getWebAnalyticsFilterPresetsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getWebAnalyticsFilterPresetsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/web_analytics_filter_presets/${shortId}/`
}

export const webAnalyticsFilterPresetsUpdate = async (
    projectId: string,
    shortId: string,
    webAnalyticsFilterPresetApi: NonReadonly<WebAnalyticsFilterPresetApi>,
    options?: RequestInit
): Promise<WebAnalyticsFilterPresetApi> => {
    return apiMutator<WebAnalyticsFilterPresetApi>(getWebAnalyticsFilterPresetsUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(webAnalyticsFilterPresetApi),
    })
}

export const getWebAnalyticsFilterPresetsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/web_analytics_filter_presets/${shortId}/`
}

export const webAnalyticsFilterPresetsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedWebAnalyticsFilterPresetApi?: NonReadonly<PatchedWebAnalyticsFilterPresetApi>,
    options?: RequestInit
): Promise<WebAnalyticsFilterPresetApi> => {
    return apiMutator<WebAnalyticsFilterPresetApi>(getWebAnalyticsFilterPresetsPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedWebAnalyticsFilterPresetApi),
    })
}

export const getWebAnalyticsFilterPresetsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/web_analytics_filter_presets/${shortId}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const webAnalyticsFilterPresetsDestroy = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getWebAnalyticsFilterPresetsDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}
