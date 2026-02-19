import { actions, kea, path, reducers, selectors } from 'kea'

import type { StatusCode, TraceSummary } from './data/mockTraceData'
import { MOCK_TRACES } from './data/mockTraceData'
import type { tracingFilterLogicType } from './tracingFilterLogicType'

const DURATION_UNITS: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000, w: 604_800_000 }

function parseDurationMs(value: string): number {
    const match = value.match(/^-?(\d+)([smhdw])$/)
    if (!match) {
        return 0
    }
    const amount = parseInt(match[1], 10)
    const ms = DURATION_UNITS[match[2]] ?? 0
    return value.startsWith('-') ? -amount * ms : amount * ms
}

export const tracingFilterLogic = kea<tracingFilterLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingFilterLogic']),

    actions({
        setSearchQuery: (query: string) => ({ query }),
        setServiceFilter: (service: string | null) => ({ service }),
        setStatusFilter: (status: StatusCode | null) => ({ status }),
        setDateFrom: (dateFrom: string | null) => ({ dateFrom }),
        setDateTo: (dateTo: string | null) => ({ dateTo }),
    }),

    reducers({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }) => query,
            },
        ],
        serviceFilter: [
            null as string | null,
            {
                setServiceFilter: (_, { service }) => service,
            },
        ],
        statusFilter: [
            null as StatusCode | null,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        dateFrom: [
            '-24h' as string | null,
            {
                setDateFrom: (_, { dateFrom }) => dateFrom,
            },
        ],
        dateTo: [
            null as string | null,
            {
                setDateTo: (_, { dateTo }) => dateTo,
            },
        ],
    }),

    selectors({
        allTraces: [() => [], (): TraceSummary[] => MOCK_TRACES],
        traces: [
            (s) => [s.allTraces, s.searchQuery, s.serviceFilter, s.statusFilter, s.dateFrom, s.dateTo],
            (
                allTraces: TraceSummary[],
                searchQuery: string,
                serviceFilter: string | null,
                statusFilter: StatusCode | null,
                dateFrom: string | null,
                dateTo: string | null
            ): TraceSummary[] => {
                let filtered = allTraces
                if (searchQuery) {
                    const q = searchQuery.toLowerCase()
                    filtered = filtered.filter(
                        (t) =>
                            t.root_span_name.toLowerCase().includes(q) ||
                            t.root_service_name.toLowerCase().includes(q) ||
                            t.trace_id.toLowerCase().includes(q)
                    )
                }
                if (serviceFilter) {
                    filtered = filtered.filter(
                        (t) =>
                            t.root_service_name === serviceFilter ||
                            t.spans.some((s) => s.service_name === serviceFilter)
                    )
                }
                if (statusFilter) {
                    filtered = filtered.filter((t) => t.status_code === statusFilter)
                }
                if (dateFrom) {
                    const fromMs = dateFrom.startsWith('-')
                        ? Date.now() + parseDurationMs(dateFrom)
                        : new Date(dateFrom).getTime()
                    if (!isNaN(fromMs)) {
                        filtered = filtered.filter((t) => new Date(t.timestamp).getTime() >= fromMs)
                    }
                }
                if (dateTo) {
                    const toMs = new Date(dateTo).getTime()
                    if (!isNaN(toMs)) {
                        filtered = filtered.filter((t) => new Date(t.timestamp).getTime() <= toMs)
                    }
                }
                return filtered
            },
        ],
    }),
])
