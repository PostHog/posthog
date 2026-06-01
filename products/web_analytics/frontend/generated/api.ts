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
    HeatmapScreenshotResponseApi,
    HeatmapsListParams,
    PaginatedHeatmapScreenshotResponseListApi,
    PaginatedHeatmapsResponseListApi,
    PaginatedWebAnalyticsFilterPresetListApi,
    PatchedHeatmapScreenshotResponseApi,
    PatchedWebAnalyticsFilterPresetApi,
    SavedListParams,
    WebAnalyticsFilterPresetApi,
    WebAnalyticsFilterPresetsListParams,
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

export const getHeatmapsListUrl = (projectId: string, params?: HeatmapsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/heatmaps/?${stringifiedParams}`
        : `/api/projects/${projectId}/heatmaps/`
}

export const heatmapsList = async (
    projectId: string,
    params?: HeatmapsListParams,
    options?: RequestInit
): Promise<PaginatedHeatmapsResponseListApi> => {
    return apiMutator<PaginatedHeatmapsResponseListApi>(getHeatmapsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getHeatmapsEventsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/heatmaps/events/`
}

export const heatmapsEventsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHeatmapsEventsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getSavedListUrl = (projectId: string, params?: SavedListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/saved/?${stringifiedParams}`
        : `/api/projects/${projectId}/saved/`
}

export const savedList = async (
    projectId: string,
    params?: SavedListParams,
    options?: RequestInit
): Promise<PaginatedHeatmapScreenshotResponseListApi> => {
    return apiMutator<PaginatedHeatmapScreenshotResponseListApi>(getSavedListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSavedCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/saved/`
}

export const savedCreate = async (
    projectId: string,
    heatmapScreenshotResponseApi: NonReadonly<HeatmapScreenshotResponseApi>,
    options?: RequestInit
): Promise<HeatmapScreenshotResponseApi> => {
    return apiMutator<HeatmapScreenshotResponseApi>(getSavedCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(heatmapScreenshotResponseApi),
    })
}

export const getSavedRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/saved/${shortId}/`
}

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

export const savedPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedHeatmapScreenshotResponseApi?: NonReadonly<PatchedHeatmapScreenshotResponseApi>,
    options?: RequestInit
): Promise<HeatmapScreenshotResponseApi> => {
    return apiMutator<HeatmapScreenshotResponseApi>(getSavedPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedHeatmapScreenshotResponseApi),
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

export const savedRegenerateCreate = async (
    projectId: string,
    shortId: string,
    heatmapScreenshotResponseApi: NonReadonly<HeatmapScreenshotResponseApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSavedRegenerateCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(heatmapScreenshotResponseApi),
    })
}

export const getWebAnalyticsWeeklyDigestUrl = (projectId: string, params?: WebAnalyticsWeeklyDigestParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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

export const getWebAnalyticsFilterPresetsListUrl = (
    projectId: string,
    params?: WebAnalyticsFilterPresetsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
