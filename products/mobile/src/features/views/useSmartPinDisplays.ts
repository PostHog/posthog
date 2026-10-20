import { useQuery } from '@tanstack/react-query'
import { useIsFocused } from 'expo-router'
import { useEffect, useMemo } from 'react'

import { fetchInsightMetadata, type InsightBasicApi } from '@/api/insights'
import { stableStringify } from '@/api/query'
import { demoAnchor, demoInsightResponse } from '@/demo/views'
import { abortError } from '@/lib/abort'
import type { InsightSnapshot, PinDisplay, PinView } from '@/model/views'

import { RECHECK_MS } from './freshness'
import {
    type DashboardSnapshot,
    dashboardContainer,
    dashboardQueryKey,
    type ItemContext,
    insightQueryKey,
    tileTarget,
} from './items'
import { listRead } from './listReads'
import { viewsQueue } from './refreshQueue'
import {
    automaticPinCandidates,
    type PinDisplayCandidate,
    type PinDisplayPrefs,
    selectPinDisplay,
} from './smartPinDisplay'
import type { RefreshList } from './useViewRefresh'
import { useViewsContext } from './useViewsContext'
import { getSnapshot, viewsKeys } from './viewsCache'

const NO_DISPLAYS: PinDisplayPrefs = {}

async function insightMetadata(
    context: ItemContext,
    shortId: string,
    signal: AbortSignal
): Promise<InsightBasicApi | undefined> {
    if (context.demo) {
        return demoInsightResponse({ shortId, dashboardRef: null, override: null }, demoAnchor())
    }
    const queryKey = viewsKeys.pinMetadata(context.scope, shortId)
    const cached = context.client.getQueryState<InsightBasicApi>(queryKey)
    if (cached?.data && Date.now() - cached.dataUpdatedAt < RECHECK_MS) {
        return cached.data
    }
    const response = await listRead('insights', signal, () => {
        if (signal.aborted) {
            throw abortError()
        }
        return fetchInsightMetadata(shortId, signal)
    })
    if (signal.aborted) {
        throw abortError()
    }
    if (response) {
        context.client.setQueryData(queryKey, response)
    }
    return response
}

async function dashboardDisplay(
    context: ItemContext,
    pin: PinView,
    signal: AbortSignal,
    group: string
): Promise<PinDisplay | null> {
    if (!pin.ref || signal.aborted) {
        return null
    }
    const ref = pin.ref
    const container = dashboardContainer(context, ref, null)
    const before = container.readAt()
    if (before === null || Date.now() - before >= RECHECK_MS) {
        await viewsQueue.enqueue({
            key: container.key,
            family: container.family,
            group,
            mode: 'force_cache',
            run: (_mode, readSignal) => container.read(readSignal),
        })
    }
    if (signal.aborted) {
        throw abortError()
    }
    const dashboard = getSnapshot<DashboardSnapshot>(context.client, dashboardQueryKey(context.scope, ref, null))
    if (!dashboard) {
        throw new Error()
    }
    const candidates = dashboard.view.tiles.flatMap((tile): PinDisplayCandidate[] => {
        const target = tileTarget(ref, tile, null)
        if (!target || tile.insightId === null || !tile.shortId) {
            return []
        }
        const snapshot = getSnapshot<InsightSnapshot>(context.client, insightQueryKey(context.scope, target))
        return snapshot
            ? [
                  {
                      display: { tileId: tile.tileId, insightId: tile.insightId, insightShortId: tile.shortId },
                      query: snapshot.query,
                      snapshot,
                  },
              ]
            : []
    })
    return selectPinDisplay(candidates)
}

export async function discoverPinDisplays(
    context: ItemContext,
    pins: readonly PinView[],
    signal: AbortSignal,
    group: string
): Promise<Record<string, PinDisplay>> {
    if (signal.aborted) {
        throw abortError()
    }
    const leave = (): void => viewsQueue.leave(group)
    signal.addEventListener('abort', leave, { once: true })
    try {
        const results = await Promise.allSettled(
            pins.map(async (pin): Promise<PinDisplay | null> => {
                if (!pin.ref || signal.aborted) {
                    return null
                }
                if (pin.kind === 'dashboard') {
                    return dashboardDisplay(context, pin, signal, group)
                }
                const insight = await insightMetadata(context, pin.ref, signal)
                return insight && !insight.deleted
                    ? selectPinDisplay([
                          {
                              display: { insightId: insight.id, insightShortId: insight.short_id },
                              query: insight.query,
                          },
                      ])
                    : null
            })
        )
        if (signal.aborted) {
            throw abortError()
        }
        const displays: Record<string, PinDisplay> = {}
        for (const [index, result] of results.entries()) {
            const pin = pins[index]
            if (pin && result.status === 'fulfilled' && result.value) {
                displays[pin.shortcutId] = result.value
            }
        }
        const failed = results.find((result) => result.status === 'rejected')
        if (Object.keys(displays).length === 0 && failed?.status === 'rejected') {
            throw failed.reason
        }
        return displays
    } finally {
        signal.removeEventListener('abort', leave)
    }
}

export function useSmartPinDisplays(
    pins: readonly PinView[] | undefined,
    displayPrefs: PinDisplayPrefs
): { displays: PinDisplayPrefs; list: RefreshList } {
    const context = useViewsContext()
    const focused = useIsFocused()
    const candidates = useMemo(() => automaticPinCandidates(pins ?? [], displayPrefs), [pins, displayPrefs])
    const signature = stableStringify(candidates.map((pin) => [pin.shortcutId, pin.kind, pin.ref]))
    const queryKey = useMemo(() => viewsKeys.smartPinDisplays(context.scope, signature), [context.scope, signature])
    const group = `${context.dataScope}|smart-pin-displays:${signature}`
    const enabled = context.ready && focused && candidates.length > 0
    const query = useQuery({
        queryKey,
        queryFn: ({ signal }) => discoverPinDisplays(context.item, candidates, signal, group),
        enabled,
        staleTime: RECHECK_MS,
        retry: false,
    })
    const { client } = context.item
    useEffect(
        () => () => {
            viewsQueue.leave(group)
            void client.cancelQueries({ queryKey, exact: true })
        },
        [client, group, queryKey]
    )
    useEffect(() => {
        if (!enabled) {
            viewsQueue.leave(group)
            void client.cancelQueries({ queryKey, exact: true })
        }
    }, [enabled, client, group, queryKey])
    const { refetch, dataUpdatedAt } = query
    const list = useMemo<RefreshList>(
        () => ({
            key: 'pin-displays',
            updatedAt: () => dataUpdatedAt,
            refetch: () => (enabled ? refetch() : Promise.resolve()),
        }),
        [dataUpdatedAt, enabled, refetch]
    )
    return { displays: query.data ?? NO_DISPLAYS, list }
}
