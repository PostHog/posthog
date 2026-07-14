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
    AppMetricsResponseApi,
    AppMetricsTotalsResponseApi,
    BlastRadiusApi,
    BlastRadiusRequestApi,
    HogFlowApi,
    HogFlowBatchJobApi,
    HogFlowInvocationApi,
    HogFlowScheduleApi,
    HogFlowTemplateApi,
    HogFlowTemplatesListParams,
    HogFlowTemplatesLogsRetrieveParams,
    HogFlowsAssetContentRetrieveParams,
    HogFlowsAssetsRetrieveParams,
    HogFlowsInvocationResultsRetrieveParams,
    HogFlowsListParams,
    HogFlowsLogsRetrieveParams,
    HogFlowsMetricsGlobalRetrieveParams,
    HogFlowsMetricsRetrieveParams,
    HogFlowsMetricsTotalsRetrieveParams,
    HogInvocationRerunRequestApi,
    HogInvocationRerunResponseApi,
    HogInvocationResultApi,
    HogInvocationResultDetailApi,
    MessageAssetApi,
    PaginatedHogFlowMinimalListApi,
    PaginatedHogFlowTemplateListApi,
    PatchedHogFlowApi,
    PatchedHogFlowGraphUpdateApi,
    PatchedHogFlowScheduleApi,
    PatchedHogFlowTemplateApi,
    WorkflowStatsRowApi,
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

export const getInternalHogFlowsProcessDueSchedulesCreateUrl = () => {
    return `/api/internal/hog_flows/process_due_schedules`
}

/**
 * Internal endpoint called by the scheduler service to process due schedules.
 * Handles both executing due schedules and initializing next_run_at for new ones.
 */
export const internalHogFlowsProcessDueSchedulesCreate = async (options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getInternalHogFlowsProcessDueSchedulesCreateUrl(), {
        ...options,
        method: 'POST',
    })
}

export const getHogFlowTemplatesListUrl = (projectId: string, params?: HogFlowTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flow_templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flow_templates/`
}

/**
 * Override list to include global templates from files alongside team templates from DB.
 */
export const hogFlowTemplatesList = async (
    projectId: string,
    params?: HogFlowTemplatesListParams,
    options?: RequestInit
): Promise<PaginatedHogFlowTemplateListApi> => {
    return apiMutator<PaginatedHogFlowTemplateListApi>(getHogFlowTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowTemplatesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/`
}

export const hogFlowTemplatesCreate = async (
    projectId: string,
    hogFlowTemplateApi: NonReadonly<HogFlowTemplateApi>,
    options?: RequestInit
): Promise<HogFlowTemplateApi> => {
    return apiMutator<HogFlowTemplateApi>(getHogFlowTemplatesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowTemplateApi),
    })
}

export const getHogFlowTemplatesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/${id}/`
}

/**
 * Check file-based global templates first, then DB team templates.
 * The queryset excludes all global templates from DB, so this only returns team templates from DB.
 */
export const hogFlowTemplatesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogFlowTemplateApi> => {
    return apiMutator<HogFlowTemplateApi>(getHogFlowTemplatesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowTemplatesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/${id}/`
}

export const hogFlowTemplatesUpdate = async (
    projectId: string,
    id: string,
    hogFlowTemplateApi: NonReadonly<HogFlowTemplateApi>,
    options?: RequestInit
): Promise<HogFlowTemplateApi> => {
    return apiMutator<HogFlowTemplateApi>(getHogFlowTemplatesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowTemplateApi),
    })
}

export const getHogFlowTemplatesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/${id}/`
}

export const hogFlowTemplatesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedHogFlowTemplateApi?: NonReadonly<PatchedHogFlowTemplateApi>,
    options?: RequestInit
): Promise<HogFlowTemplateApi> => {
    return apiMutator<HogFlowTemplateApi>(getHogFlowTemplatesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedHogFlowTemplateApi),
    })
}

export const getHogFlowTemplatesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/${id}/`
}

export const hogFlowTemplatesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogFlowTemplatesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getHogFlowTemplatesLogsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: HogFlowTemplatesLogsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flow_templates/${id}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flow_templates/${id}/logs/`
}

export const hogFlowTemplatesLogsRetrieve = async (
    projectId: string,
    id: string,
    params?: HogFlowTemplatesLogsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFlowTemplatesLogsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsListUrl = (projectId: string, params?: HogFlowsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/`
}

export const hogFlowsList = async (
    projectId: string,
    params?: HogFlowsListParams,
    options?: RequestInit
): Promise<PaginatedHogFlowMinimalListApi> => {
    return apiMutator<PaginatedHogFlowMinimalListApi>(getHogFlowsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hog_flows/`
}

export const hogFlowsCreate = async (
    projectId: string,
    hogFlowApi: NonReadonly<HogFlowApi>,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowApi),
    })
}

export const getHogFlowsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/`
}

export const hogFlowsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/`
}

export const hogFlowsUpdate = async (
    projectId: string,
    id: string,
    hogFlowApi: NonReadonly<HogFlowApi>,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowApi),
    })
}

export const getHogFlowsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/`
}

export const hogFlowsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedHogFlowApi?: NonReadonly<PatchedHogFlowApi>,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedHogFlowApi),
    })
}

export const getHogFlowsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/`
}

export const hogFlowsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogFlowsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getHogFlowsAssetsRetrieveUrl = (projectId: string, id: string, params?: HogFlowsAssetsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/${id}/assets/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/${id}/assets/`
}

export const hogFlowsAssetsRetrieve = async (
    projectId: string,
    id: string,
    params?: HogFlowsAssetsRetrieveParams,
    options?: RequestInit
): Promise<MessageAssetApi[]> => {
    return apiMutator<MessageAssetApi[]>(getHogFlowsAssetsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsAssetContentRetrieveUrl = (
    projectId: string,
    id: string,
    params: HogFlowsAssetContentRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/${id}/assets/content/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/${id}/assets/content/`
}

export const hogFlowsAssetContentRetrieve = async (
    projectId: string,
    id: string,
    params: HogFlowsAssetContentRetrieveParams,
    options?: RequestInit
): Promise<string> => {
    return apiMutator<string>(getHogFlowsAssetContentRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsBatchJobsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/batch_jobs/`
}

export const hogFlowsBatchJobsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogFlowBatchJobApi[]> => {
    return apiMutator<HogFlowBatchJobApi[]>(getHogFlowsBatchJobsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsBatchJobsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/batch_jobs/`
}

export const hogFlowsBatchJobsCreate = async (
    projectId: string,
    id: string,
    hogFlowBatchJobApi: NonReadonly<HogFlowBatchJobApi>,
    options?: RequestInit
): Promise<HogFlowBatchJobApi> => {
    return apiMutator<HogFlowBatchJobApi>(getHogFlowsBatchJobsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowBatchJobApi),
    })
}

export const getHogFlowsGraphPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/graph/`
}

export const hogFlowsGraphPartialUpdate = async (
    projectId: string,
    id: string,
    patchedHogFlowGraphUpdateApi?: PatchedHogFlowGraphUpdateApi,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsGraphPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedHogFlowGraphUpdateApi),
    })
}

export const getHogFlowsInvocationResultsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: HogFlowsInvocationResultsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/${id}/invocation_results/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/${id}/invocation_results/`
}

export const hogFlowsInvocationResultsRetrieve = async (
    projectId: string,
    id: string,
    params?: HogFlowsInvocationResultsRetrieveParams,
    options?: RequestInit
): Promise<HogInvocationResultApi[]> => {
    return apiMutator<HogInvocationResultApi[]>(getHogFlowsInvocationResultsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsInvocationResultRetrieveUrl = (projectId: string, id: string, invocationId: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/invocation_results/${invocationId}/`
}

export const hogFlowsInvocationResultRetrieve = async (
    projectId: string,
    id: string,
    invocationId: string,
    options?: RequestInit
): Promise<HogInvocationResultDetailApi> => {
    return apiMutator<HogInvocationResultDetailApi>(
        getHogFlowsInvocationResultRetrieveUrl(projectId, id, invocationId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getHogFlowsInvocationsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/invocations/`
}

export const hogFlowsInvocationsCreate = async (
    projectId: string,
    id: string,
    hogFlowInvocationApi?: NonReadonly<HogFlowInvocationApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFlowsInvocationsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowInvocationApi),
    })
}

export const getHogFlowsLogsRetrieveUrl = (projectId: string, id: string, params?: HogFlowsLogsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/${id}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/${id}/logs/`
}

export const hogFlowsLogsRetrieve = async (
    projectId: string,
    id: string,
    params?: HogFlowsLogsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFlowsLogsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsMetricsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: HogFlowsMetricsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/${id}/metrics/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/${id}/metrics/`
}

export const hogFlowsMetricsRetrieve = async (
    projectId: string,
    id: string,
    params?: HogFlowsMetricsRetrieveParams,
    options?: RequestInit
): Promise<AppMetricsResponseApi> => {
    return apiMutator<AppMetricsResponseApi>(getHogFlowsMetricsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsMetricsTotalsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: HogFlowsMetricsTotalsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/${id}/metrics/totals/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/${id}/metrics/totals/`
}

export const hogFlowsMetricsTotalsRetrieve = async (
    projectId: string,
    id: string,
    params?: HogFlowsMetricsTotalsRetrieveParams,
    options?: RequestInit
): Promise<AppMetricsTotalsResponseApi> => {
    return apiMutator<AppMetricsTotalsResponseApi>(getHogFlowsMetricsTotalsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsRerunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/rerun/`
}

/**
 * Rerun past invocations of this hog flow from their stored payloads.
 *
 * Same shape and semantics as the hog function rerun endpoint —
 * proxies through to the CDP worker, which reads matching rows from
 * ClickHouse, rehydrates from `invocation_globals`, and re-enqueues
 * onto cyclotron with `is_retry=1`.
 *
 * Because rerun replays historical event/person/group data, it requires
 * `person:read` and `group:read` on top of `hog_flow:write`.
 */
export const hogFlowsRerunCreate = async (
    projectId: string,
    id: string,
    hogInvocationRerunRequestApi: HogInvocationRerunRequestApi,
    options?: RequestInit
): Promise<HogInvocationRerunResponseApi> => {
    return apiMutator<HogInvocationRerunResponseApi>(getHogFlowsRerunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogInvocationRerunRequestApi),
    })
}

export const getHogFlowsSchedulesListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/schedules/`
}

export const hogFlowsSchedulesList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogFlowScheduleApi[]> => {
    return apiMutator<HogFlowScheduleApi[]>(getHogFlowsSchedulesListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsSchedulesCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/schedules/`
}

export const hogFlowsSchedulesCreate = async (
    projectId: string,
    id: string,
    hogFlowScheduleApi: NonReadonly<HogFlowScheduleApi>,
    options?: RequestInit
): Promise<HogFlowScheduleApi> => {
    return apiMutator<HogFlowScheduleApi>(getHogFlowsSchedulesCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowScheduleApi),
    })
}

export const getHogFlowsSchedulesPartialUpdateUrl = (projectId: string, id: string, scheduleId: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/schedules/${scheduleId}/`
}

export const hogFlowsSchedulesPartialUpdate = async (
    projectId: string,
    id: string,
    scheduleId: string,
    patchedHogFlowScheduleApi?: NonReadonly<PatchedHogFlowScheduleApi>,
    options?: RequestInit
): Promise<HogFlowScheduleApi> => {
    return apiMutator<HogFlowScheduleApi>(getHogFlowsSchedulesPartialUpdateUrl(projectId, id, scheduleId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedHogFlowScheduleApi),
    })
}

export const getHogFlowsSchedulesDestroyUrl = (projectId: string, id: string, scheduleId: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/schedules/${scheduleId}/`
}

export const hogFlowsSchedulesDestroy = async (
    projectId: string,
    id: string,
    scheduleId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFlowsSchedulesDestroyUrl(projectId, id, scheduleId), {
        ...options,
        method: 'DELETE',
    })
}

export const getHogFlowsBulkDeleteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hog_flows/bulk_delete/`
}

export const hogFlowsBulkDeleteCreate = async (
    projectId: string,
    hogFlowApi: NonReadonly<HogFlowApi>,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsBulkDeleteCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowApi),
    })
}

export const getHogFlowsMetricsGlobalRetrieveUrl = (
    projectId: string,
    params?: HogFlowsMetricsGlobalRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/metrics/global/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/metrics/global/`
}

export const hogFlowsMetricsGlobalRetrieve = async (
    projectId: string,
    params?: HogFlowsMetricsGlobalRetrieveParams,
    options?: RequestInit
): Promise<WorkflowStatsRowApi[]> => {
    return apiMutator<WorkflowStatsRowApi[]>(getHogFlowsMetricsGlobalRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsUserBlastRadiusCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hog_flows/user_blast_radius/`
}

export const hogFlowsUserBlastRadiusCreate = async (
    projectId: string,
    blastRadiusRequestApi: BlastRadiusRequestApi,
    options?: RequestInit
): Promise<BlastRadiusApi> => {
    return apiMutator<BlastRadiusApi>(getHogFlowsUserBlastRadiusCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(blastRadiusRequestApi),
    })
}

export const getInternalHogFlowsBatchJobsStatusUpdateUrl = (teamId: string, batchJobId: string) => {
    return `/api/projects/${teamId}/internal/hog_flows/batch_jobs/${batchJobId}/status`
}

/**
 * Internal endpoint for the Node-side batch resolver to write the terminal
 * status of a HogFlowBatchJob run. Idempotent: if the row is already in a
 * terminal status, returns 200 without re-writing — the resolver retries
 * this call via cyclotron retry semantics, so safe repeats are required.
 *
 * Accepts: { status: "completed" | "failed" }
 */
export const internalHogFlowsBatchJobsStatusUpdate = async (
    teamId: string,
    batchJobId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInternalHogFlowsBatchJobsStatusUpdateUrl(teamId, batchJobId), {
        ...options,
        method: 'PUT',
    })
}

export const getInternalHogFlowsUserBlastRadiusCreateUrl = (teamId: string) => {
    return `/api/projects/${teamId}/internal/hog_flows/user_blast_radius`
}

/**
 * Internal endpoint for Node.js services to query user blast radius.
 * Requires Bearer token authentication via INTERNAL_API_SECRET.
 */
export const internalHogFlowsUserBlastRadiusCreate = async (teamId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getInternalHogFlowsUserBlastRadiusCreateUrl(teamId), {
        ...options,
        method: 'POST',
    })
}

export const getInternalHogFlowsUserBlastRadiusPersonsCreateUrl = (teamId: string) => {
    return `/api/projects/${teamId}/internal/hog_flows/user_blast_radius_persons`
}

/**
 * Internal endpoint for Node.js services to query user blast radius persons with pagination.
 * Requires Bearer token authentication via INTERNAL_API_SECRET.
 */
export const internalHogFlowsUserBlastRadiusPersonsCreate = async (
    teamId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInternalHogFlowsUserBlastRadiusPersonsCreateUrl(teamId), {
        ...options,
        method: 'POST',
    })
}
