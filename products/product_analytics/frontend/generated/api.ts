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
    BulkUpdateTagsRequestApi,
    BulkUpdateTagsResponseApi,
    ColumnConfigurationApi,
    ColumnConfigurationsListParams,
    ElementApi,
    ElementsListParams,
    InsightApi,
    InsightsActivityRetrieveParams,
    InsightsAllActivityRetrieveParams,
    InsightsAnalyzeRetrieveParams,
    InsightsBulkUpdateTagsCreateParams,
    InsightsCancelCreateParams,
    InsightsCreateParams,
    InsightsDestroyParams,
    InsightsGenerateMetadataCreateParams,
    InsightsListParams,
    InsightsMyLastViewedRetrieveParams,
    InsightsPartialUpdateParams,
    InsightsRetrieveParams,
    InsightsSuggestionsCreateParams,
    InsightsSuggestionsRetrieveParams,
    InsightsTrendingRetrieveParams,
    InsightsUpdateParams,
    InsightsViewedCreateParams,
    PaginatedColumnConfigurationListApi,
    PaginatedElementListApi,
    PaginatedInsightListApi,
    PatchedColumnConfigurationApi,
    PatchedElementApi,
    PatchedInsightApi,
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

export const getColumnConfigurationsListUrl = (projectId: string, params?: ColumnConfigurationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/column_configurations/?${stringifiedParams}`
        : `/api/environments/${projectId}/column_configurations/`
}

export const columnConfigurationsList = async (
    projectId: string,
    params?: ColumnConfigurationsListParams,
    options?: RequestInit
): Promise<PaginatedColumnConfigurationListApi> => {
    return apiMutator<PaginatedColumnConfigurationListApi>(getColumnConfigurationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getColumnConfigurationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/column_configurations/`
}

export const columnConfigurationsCreate = async (
    projectId: string,
    columnConfigurationApi: NonReadonly<ColumnConfigurationApi>,
    options?: RequestInit
): Promise<ColumnConfigurationApi> => {
    return apiMutator<ColumnConfigurationApi>(getColumnConfigurationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(columnConfigurationApi),
    })
}

export const getColumnConfigurationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ColumnConfigurationApi> => {
    return apiMutator<ColumnConfigurationApi>(getColumnConfigurationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getColumnConfigurationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsUpdate = async (
    projectId: string,
    id: string,
    columnConfigurationApi: NonReadonly<ColumnConfigurationApi>,
    options?: RequestInit
): Promise<ColumnConfigurationApi> => {
    return apiMutator<ColumnConfigurationApi>(getColumnConfigurationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(columnConfigurationApi),
    })
}

export const getColumnConfigurationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedColumnConfigurationApi: NonReadonly<PatchedColumnConfigurationApi>,
    options?: RequestInit
): Promise<ColumnConfigurationApi> => {
    return apiMutator<ColumnConfigurationApi>(getColumnConfigurationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedColumnConfigurationApi),
    })
}

export const getColumnConfigurationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getColumnConfigurationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getElementsListUrl = (projectId: string, params?: ElementsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/elements/?${stringifiedParams}`
        : `/api/projects/${projectId}/elements/`
}

export const elementsList = async (
    projectId: string,
    params?: ElementsListParams,
    options?: RequestInit
): Promise<PaginatedElementListApi> => {
    return apiMutator<PaginatedElementListApi>(getElementsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getElementsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/elements/`
}

export const elementsCreate = async (
    projectId: string,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export const getElementsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsRetrieve = async (projectId: string, id: number, options?: RequestInit): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getElementsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsUpdate = async (
    projectId: string,
    id: number,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export const getElementsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedElementApi: PatchedElementApi,
    options?: RequestInit
): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedElementApi),
    })
}

export const getElementsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getElementsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * The original version of this API always and only returned $autocapture elements
If no include query parameter is sent this remains true.
Now, you can pass a combination of include query parameters to get different types of elements
Currently only $autocapture and $rageclick and $dead_click are supported
 */
export const getElementsStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/elements/stats/`
}

export const elementsStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getElementsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getElementsValuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/elements/values/`
}

export const elementsValuesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getElementsValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsListUrl = (projectId: string, params?: InsightsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/`
}

export const insightsList = async (
    projectId: string,
    params?: InsightsListParams,
    options?: RequestInit
): Promise<PaginatedInsightListApi> => {
    return apiMutator<PaginatedInsightListApi>(getInsightsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsCreateUrl = (projectId: string, params?: InsightsCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/`
}

export const insightsCreate = async (
    projectId: string,
    insightApi: NonReadonly<InsightApi>,
    params?: InsightsCreateParams,
    options?: RequestInit
): Promise<InsightApi> => {
    return apiMutator<InsightApi>(getInsightsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(insightApi),
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsRetrieveUrl = (projectId: string, id: number | string, params?: InsightsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/${id}/`
}

export const insightsRetrieve = async (
    projectId: string,
    id: number | string,
    params?: InsightsRetrieveParams,
    options?: RequestInit
): Promise<InsightApi> => {
    return apiMutator<InsightApi>(getInsightsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsUpdateUrl = (projectId: string, id: number | string, params?: InsightsUpdateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/${id}/`
}

export const insightsUpdate = async (
    projectId: string,
    id: number | string,
    insightApi: NonReadonly<InsightApi>,
    params?: InsightsUpdateParams,
    options?: RequestInit
): Promise<InsightApi> => {
    return apiMutator<InsightApi>(getInsightsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(insightApi),
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsPartialUpdateUrl = (
    projectId: string,
    id: number | string,
    params?: InsightsPartialUpdateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/${id}/`
}

export const insightsPartialUpdate = async (
    projectId: string,
    id: number | string,
    patchedInsightApi: NonReadonly<PatchedInsightApi>,
    params?: InsightsPartialUpdateParams,
    options?: RequestInit
): Promise<InsightApi> => {
    return apiMutator<InsightApi>(getInsightsPartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedInsightApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getInsightsDestroyUrl = (projectId: string, id: number | string, params?: InsightsDestroyParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/${id}/`
}

export const insightsDestroy = async (
    projectId: string,
    id: number | string,
    params?: InsightsDestroyParams,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getInsightsDestroyUrl(projectId, id, params), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsActivityRetrieveUrl = (
    projectId: string,
    id: number,
    params?: InsightsActivityRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/${id}/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/${id}/activity/`
}

export const insightsActivityRetrieve = async (
    projectId: string,
    id: number,
    params?: InsightsActivityRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsActivityRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsAnalyzeRetrieveUrl = (
    projectId: string,
    id: number,
    params?: InsightsAnalyzeRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/${id}/analyze/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/${id}/analyze/`
}

export const insightsAnalyzeRetrieve = async (
    projectId: string,
    id: number,
    params?: InsightsAnalyzeRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsAnalyzeRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsSuggestionsRetrieveUrl = (
    projectId: string,
    id: number,
    params?: InsightsSuggestionsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/${id}/suggestions/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/${id}/suggestions/`
}

export const insightsSuggestionsRetrieve = async (
    projectId: string,
    id: number,
    params?: InsightsSuggestionsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsSuggestionsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsSuggestionsCreateUrl = (
    projectId: string,
    id: number,
    params?: InsightsSuggestionsCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/${id}/suggestions/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/${id}/suggestions/`
}

export const insightsSuggestionsCreate = async (
    projectId: string,
    id: number,
    insightApi: NonReadonly<InsightApi>,
    params?: InsightsSuggestionsCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsSuggestionsCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(insightApi),
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsAllActivityRetrieveUrl = (projectId: string, params?: InsightsAllActivityRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/activity/`
}

export const insightsAllActivityRetrieve = async (
    projectId: string,
    params?: InsightsAllActivityRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsAllActivityRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const getInsightsBulkUpdateTagsCreateUrl = (projectId: string, params?: InsightsBulkUpdateTagsCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/bulk_update_tags/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/bulk_update_tags/`
}

export const insightsBulkUpdateTagsCreate = async (
    projectId: string,
    bulkUpdateTagsRequestApi: BulkUpdateTagsRequestApi,
    params?: InsightsBulkUpdateTagsCreateParams,
    options?: RequestInit
): Promise<BulkUpdateTagsResponseApi> => {
    return apiMutator<BulkUpdateTagsResponseApi>(getInsightsBulkUpdateTagsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkUpdateTagsRequestApi),
    })
}

/**
 * DRF ViewSet mixin that gates coalesced responses behind permission checks.

The QueryCoalescingMiddleware attaches cached response data to
request.META["_coalesced_response"] for followers. This mixin runs DRF's
initial() (auth + permissions + throttling) before returning the
cached response, ensuring the request is authorized.
 */
export const getInsightsCancelCreateUrl = (projectId: string, params?: InsightsCancelCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/cancel/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/cancel/`
}

export const insightsCancelCreate = async (
    projectId: string,
    insightApi: NonReadonly<InsightApi>,
    params?: InsightsCancelCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsCancelCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(insightApi),
    })
}

/**
 * Generate an AI-suggested name and description for an insight based on its query configuration.
 */
export const getInsightsGenerateMetadataCreateUrl = (
    projectId: string,
    params?: InsightsGenerateMetadataCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/generate_metadata/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/generate_metadata/`
}

export const insightsGenerateMetadataCreate = async (
    projectId: string,
    insightApi: NonReadonly<InsightApi>,
    params?: InsightsGenerateMetadataCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsGenerateMetadataCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(insightApi),
    })
}

/**
 * Returns basic details about the last 5 insights viewed by this user. Most recently viewed first.
 */
export const getInsightsMyLastViewedRetrieveUrl = (projectId: string, params?: InsightsMyLastViewedRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/my_last_viewed/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/my_last_viewed/`
}

export const insightsMyLastViewedRetrieve = async (
    projectId: string,
    params?: InsightsMyLastViewedRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsMyLastViewedRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns trending insights based on view count in the last N days (default 7).
Defaults to returning top 10 insights.
 */
export const getInsightsTrendingRetrieveUrl = (projectId: string, params?: InsightsTrendingRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/trending/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/trending/`
}

export const insightsTrendingRetrieve = async (
    projectId: string,
    params?: InsightsTrendingRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsTrendingRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update insight view timestamps.
Expects: {"insight_ids": [1, 2, 3, ...]}
 */
export const getInsightsViewedCreateUrl = (projectId: string, params?: InsightsViewedCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insights/viewed/?${stringifiedParams}`
        : `/api/projects/${projectId}/insights/viewed/`
}

export const insightsViewedCreate = async (
    projectId: string,
    insightApi: NonReadonly<InsightApi>,
    params?: InsightsViewedCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsViewedCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(insightApi),
    })
}
