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
import type { PaginatedSignalReportListApi, SignalReportApi, SignalReportsListParams } from './api.schemas'

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

/**
 * Run the video segment clustering workflow for this team. DEBUG only. Blocks until workflow completes.
 * @summary Run session analysis
 */
export const getSignalReportsAnalyzeSessionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signal_reports/analyze_sessions/`
}

export const signalReportsAnalyzeSessionsCreate = async (
    projectId: string,
    signalReportApi: NonReadonly<SignalReportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSignalReportsAnalyzeSessionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(signalReportApi),
    })
}
