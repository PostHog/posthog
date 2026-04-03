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
    HogFlowApi,
    HogFlowTemplateApi,
    HogFlowTemplatesListParams,
    HogFlowsListParams,
    HogFlowsSchedulesCreateParams,
    HogFlowsSchedulesListParams,
    PaginatedHogFlowMinimalListApi,
    PaginatedHogFlowScheduleListApi,
    PaginatedHogFlowTemplateListApi,
    PatchedHogFlowApi,
    PatchedHogFlowTemplateApi,
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

/**
 * Override list to include global templates from files alongside team templates from DB.
 */
export const getHogFlowTemplatesListUrl = (projectId: string, params?: HogFlowTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flow_templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flow_templates/`
}

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

/**
 * Check file-based global templates first, then DB team templates.
The queryset excludes all global templates from DB, so this only returns team templates from DB.
 */
export const getHogFlowTemplatesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/${id}/`
}

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
    patchedHogFlowTemplateApi: NonReadonly<PatchedHogFlowTemplateApi>,
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

export const getHogFlowTemplatesLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/${id}/logs/`
}

export const hogFlowTemplatesLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFlowTemplatesLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsListUrl = (projectId: string, params?: HogFlowsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
    patchedHogFlowApi: NonReadonly<PatchedHogFlowApi>,
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

export const getHogFlowsBatchJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/batch_jobs/`
}

export const hogFlowsBatchJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsBatchJobsRetrieveUrl(projectId, id), {
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
    hogFlowApi: NonReadonly<HogFlowApi>,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsBatchJobsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowApi),
    })
}

export const getHogFlowsInvocationsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/invocations/`
}

export const hogFlowsInvocationsCreate = async (
    projectId: string,
    id: string,
    hogFlowApi: NonReadonly<HogFlowApi>,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsInvocationsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowApi),
    })
}

export const getHogFlowsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/logs/`
}

export const hogFlowsLogsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogFlowsLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsMetricsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/metrics/`
}

export const hogFlowsMetricsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogFlowsMetricsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsMetricsTotalsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/metrics/totals/`
}

export const hogFlowsMetricsTotalsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFlowsMetricsTotalsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsSchedulesListUrl = (projectId: string, id: string, params?: HogFlowsSchedulesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/${id}/schedules/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/${id}/schedules/`
}

export const hogFlowsSchedulesList = async (
    projectId: string,
    id: string,
    params?: HogFlowsSchedulesListParams,
    options?: RequestInit
): Promise<PaginatedHogFlowScheduleListApi> => {
    return apiMutator<PaginatedHogFlowScheduleListApi>(getHogFlowsSchedulesListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsSchedulesCreateUrl = (
    projectId: string,
    id: string,
    params?: HogFlowsSchedulesCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_flows/${id}/schedules/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_flows/${id}/schedules/`
}

export const hogFlowsSchedulesCreate = async (
    projectId: string,
    id: string,
    hogFlowApi: NonReadonly<HogFlowApi>,
    params?: HogFlowsSchedulesCreateParams,
    options?: RequestInit
): Promise<PaginatedHogFlowScheduleListApi> => {
    return apiMutator<PaginatedHogFlowScheduleListApi>(getHogFlowsSchedulesCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowApi),
    })
}

export const getHogFlowsSchedulesPartialUpdateUrl = (projectId: string, id: string, scheduleId: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/schedules/${scheduleId}/`
}

export const hogFlowsSchedulesPartialUpdate = async (
    projectId: string,
    id: string,
    scheduleId: string,
    patchedHogFlowApi: NonReadonly<PatchedHogFlowApi>,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsSchedulesPartialUpdateUrl(projectId, id, scheduleId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedHogFlowApi),
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

export const getHogFlowsUserBlastRadiusCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hog_flows/user_blast_radius/`
}

export const hogFlowsUserBlastRadiusCreate = async (
    projectId: string,
    hogFlowApi: NonReadonly<HogFlowApi>,
    options?: RequestInit
): Promise<HogFlowApi> => {
    return apiMutator<HogFlowApi>(getHogFlowsUserBlastRadiusCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFlowApi),
    })
}
