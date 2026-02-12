/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type { PaginatedSignalReportListApi, SignalReportsListParams } from './api.schemas'

export const getSignalsEmitCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/signals/emit/`
}

export const signalsEmitCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSignalsEmitCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

/**
 * API for reading signal reports. Reports are auto-generated from video segment clustering.
 */
export const getSignalReportsListUrl = (projectId: string, params?: SignalReportsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signal_reports/?${stringifiedParams}`
        : `/api/projects/${projectId}/signal_reports/`
}

export const signalReportsList = async (
    projectId: string,
    params?: SignalReportsListParams,
    options?: RequestInit
): Promise<PaginatedSignalReportListApi> => {
    return apiMutator<PaginatedSignalReportListApi>(getSignalReportsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
