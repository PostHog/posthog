// The screen and the inbox prefetcher share these, so a prefetched entry is the one the screen reads.
import {
    type DefaultError,
    type QueryKey,
    type QueryKeyWithDataTag,
    queryOptions,
    type UnusedSkipTokenOptions,
} from '@tanstack/react-query'

import {
    fetchReport,
    fetchReportArtefacts,
    fetchReportSignals,
    type PaginatedApi,
    type ProjectScope,
    type ReportArtefactApi,
    type ReportSignalsApi,
    reportKeys,
    retryUnlessMissing,
    type SignalReportApi,
} from '@/api/reports'
import { fetchReportPage, type ReportPageApi } from '@/api/today'

type ReportQueryOptions<TData, TKey extends QueryKey> = UnusedSkipTokenOptions<TData, DefaultError, TData, TKey> &
    QueryKeyWithDataTag<TKey, TData, DefaultError>

export function reportDetailQuery(
    scope: ProjectScope | null,
    reportId: string
): ReportQueryOptions<SignalReportApi, ReturnType<typeof reportKeys.detail>> {
    return queryOptions({
        queryKey: reportKeys.detail(scope, reportId),
        queryFn: ({ signal }) => fetchReport(reportId, signal),
    })
}

export function reportArtefactsQuery(
    scope: ProjectScope | null,
    reportId: string
): ReportQueryOptions<PaginatedApi<ReportArtefactApi>, ReturnType<typeof reportKeys.artefacts>> {
    return queryOptions({
        queryKey: reportKeys.artefacts(scope, reportId),
        queryFn: ({ signal }) => fetchReportArtefacts(reportId, signal),
    })
}

export function reportPageQuery(
    scope: ProjectScope | null,
    reportId: string
): ReportQueryOptions<ReportPageApi, ReturnType<typeof reportKeys.page>> {
    // Without the type arguments, `retryUnlessMissing`'s `unknown` error parameter widens the error type.
    return queryOptions<ReportPageApi, DefaultError, ReportPageApi, ReturnType<typeof reportKeys.page>>({
        queryKey: reportKeys.page(scope, reportId),
        queryFn: ({ signal }) => fetchReportPage(reportId, signal),
        retry: retryUnlessMissing,
    })
}

export function reportSignalsQuery(
    scope: ProjectScope | null,
    reportId: string
): ReportQueryOptions<ReportSignalsApi, ReturnType<typeof reportKeys.signals>> {
    return queryOptions({
        queryKey: reportKeys.signals(scope, reportId),
        queryFn: ({ signal }) => fetchReportSignals(reportId, signal),
    })
}
