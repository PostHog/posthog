import { type Query, useQuery, useQueryClient } from '@tanstack/react-query'
import { getCalendars } from 'expo-localization'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { NotSignedInError } from '@/api/client'
import {
    fetchInboxReports,
    type ProjectScope,
    postReadStates,
    READ_STATE_BATCH,
    type ReadStatesApi,
    reportKeys,
    retryUnlessMissing,
} from '@/api/reports'
import { type BriefingApi, fetchBriefing } from '@/api/today'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode, useDemoMode } from '@/demo/demoMode'
import { useDemoInboxQuery } from '@/demo/hooks'
import { track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import { useNow } from '@/lib/useNow'
import {
    inboxFromBriefing,
    inboxFromReports,
    signalCountsFromBriefing,
    signalCountsFromReports,
} from '@/model/adapters/inbox'
import { errorQuery, loadingQuery } from '@/model/queryStates'
import type { InboxItem, QueryState } from '@/model/types'

import { useSnoozeEntries, wakeSnooze } from '../snooze/hooks'
import { applySnoozes } from '../snooze/snoozeEntries'

const BRIEFING_POLL_MS = 5_000
const MAX_BRIEFING_POLLS = 132

function deviceTimeZone(): string | null {
    try {
        return getCalendars()[0]?.timeZone ?? null
    } catch {
        return null
    }
}

function isSettled(briefing: BriefingApi): boolean {
    return briefing.status === 'ready' || briefing.status === 'failed'
}

function pollWhileWriting(query: Query<BriefingApi, Error>): number | false {
    const briefing = query.state.data
    if (!briefing || isSettled(briefing) || query.state.dataUpdateCount >= MAX_BRIEFING_POLLS) {
        return false
    }
    return BRIEFING_POLL_MS
}

function needsFallback(briefing: BriefingApi | undefined, briefingError: boolean, briefingItems: number): boolean {
    if (briefingError) {
        return true
    }
    return briefing !== undefined && briefingItems === 0 && briefing.status !== 'ready'
}

async function fetchReadStates(ids: readonly string[]): Promise<Record<string, boolean>> {
    const batches: string[][] = []
    for (let start = 0; start < ids.length; start += READ_STATE_BATCH) {
        batches.push(ids.slice(start, start + READ_STATE_BATCH))
    }
    const responses = await Promise.all(batches.map((batch) => postReadStates(batch)))
    return Object.assign({}, ...responses.map((response: ReadStatesApi) => response.states))
}

function useLiveInboxItems(enabled: boolean): QueryState<InboxItem[]> {
    const scope = useProjectScope()
    const active = enabled && scope !== null
    const timezone = useMemo(deviceTimeZone, [])
    const now = useNow()
    const snoozes = useSnoozeEntries()
    const [pulling, setPulling] = useState(false)

    const briefing = useQuery({
        queryKey: reportKeys.briefing(scope, timezone),
        queryFn: ({ signal }) => fetchBriefing(timezone, signal),
        enabled: active,
        retry: retryUnlessMissing,
        refetchInterval: pollWhileWriting,
    })
    const briefingItems = useMemo(() => (briefing.data ? inboxFromBriefing(briefing.data) : undefined), [briefing.data])
    // A failed poll keeps the briefing it already has; only a briefing that never loaded falls back.
    const briefingMissing = briefing.isError && briefing.data === undefined
    const fallbackNeeded = needsFallback(briefing.data, briefingMissing, briefingItems?.length ?? 0)
    const fallback = useQuery({
        queryKey: reportKeys.inbox(scope),
        queryFn: ({ signal }) => fetchInboxReports(signal),
        enabled: active && fallbackNeeded,
    })
    const fallbackItems = useMemo(
        () => (fallback.data ? inboxFromReports(fallback.data.results) : undefined),
        [fallback.data]
    )
    const baseItems = fallbackNeeded ? fallbackItems : briefingItems
    const signalCounts = useMemo(() => {
        if (fallbackNeeded) {
            return fallback.data ? signalCountsFromReports(fallback.data.results) : {}
        }
        return briefing.data ? signalCountsFromBriefing(briefing.data) : {}
    }, [fallbackNeeded, fallback.data, briefing.data])

    const ids = useMemo(() => [...new Set((baseItems ?? []).map((item) => item.reportId))].sort(), [baseItems])
    const readStates = useQuery({
        queryKey: reportKeys.readStates(scope, ids),
        queryFn: () => fetchReadStates(ids),
        enabled: active && ids.length > 0,
        retry: retryUnlessMissing,
    })

    const items = useMemo(() => {
        if (!baseItems || !scope) {
            return undefined
        }
        const withRead = baseItems.map((item) => ({ ...item, read: readStates.data?.[item.reportId] ?? item.read }))
        return applySnoozes(withRead, snoozes, scope, now, signalCounts)
    }, [baseItems, readStates.data, snoozes, scope, now, signalCounts])

    const { refetch: refetchBriefing } = briefing
    const { refetch: refetchFallback } = fallback
    const { refetch: refetchReadStates } = readStates
    const refetch = useCallback(async (): Promise<void> => {
        setPulling(true)
        try {
            await Promise.all([
                refetchBriefing(),
                fallbackNeeded ? refetchFallback() : Promise.resolve(),
                ids.length > 0 ? refetchReadStates() : Promise.resolve(),
            ])
        } finally {
            setPulling(false)
        }
    }, [refetchBriefing, refetchFallback, refetchReadStates, fallbackNeeded, ids.length])

    if (!scope) {
        return errorQuery(new NotSignedInError())
    }
    if (items) {
        return { data: items, isLoading: false, isError: false, error: null, isRefetching: pulling, refetch }
    }
    if (fallbackNeeded && fallback.isError) {
        return errorQuery(toError(fallback.error), refetch)
    }
    return { ...loadingQuery<InboxItem[]>(), refetch }
}

export function useInboxItems(): QueryState<InboxItem[]> {
    const mode = useDataMode()
    const demoQuery = useDemoInboxQuery()
    const liveQuery = useLiveInboxItems(mode === 'live')
    if (mode === 'loading') {
        return loadingQuery()
    }
    if (mode === 'demo') {
        return demoQuery
    }
    return liveQuery
}

function setCachedRead(
    queryClient: ReturnType<typeof useQueryClient>,
    scope: ProjectScope,
    reportId: string,
    read: boolean
): void {
    queryClient.setQueriesData<Record<string, boolean>>({ queryKey: reportKeys.readStatesAll(scope) }, (states) =>
        states && reportId in states ? { ...states, [reportId]: read } : states
    )
}

async function markReportRead(
    queryClient: ReturnType<typeof useQueryClient>,
    scope: ProjectScope,
    reportId: string
): Promise<void> {
    setCachedRead(queryClient, scope, reportId, true)
    try {
        await postReadStates([reportId], true)
    } catch (error) {
        void queryClient.invalidateQueries({ queryKey: reportKeys.readStatesAll(scope) })
        throw error
    }
    track('mobile_report_marked_read', { report_id: reportId })
}

export function useMarkReadAction(reportId: string): AsyncAction<[]> {
    const demo = useDemoMode((state) => state.enabled)
    const demoMarkRead = useDemoMode((state) => state.markRead)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    return useAsyncAction(async () => {
        if (demo) {
            demoMarkRead(reportId)
            return
        }
        if (!scope) {
            throw new NotSignedInError()
        }
        await markReportRead(queryClient, scope, reportId)
    })
}

// Posts without `useAsyncAction`, whose in-flight guard would drop the next report's post on a fast Prev/Next.
export function useMarkReadOnOpen(reportId: string): void {
    const demo = useDemoMode((state) => state.enabled)
    const demoMarkRead = useDemoMode((state) => state.markRead)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    useEffect(() => {
        if (demo) {
            demoMarkRead(reportId)
            return
        }
        if (!scope) {
            return
        }
        markReportRead(queryClient, scope, reportId).catch(() => undefined)
        wakeSnooze(scope, reportId).catch(() => undefined)
    }, [reportId, demo, demoMarkRead, scope, queryClient])
}
