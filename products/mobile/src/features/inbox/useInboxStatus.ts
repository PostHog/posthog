import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { fetchInboxStatus, type InboxStatusApi, inboxStatusKey } from '@/api/inboxStatus'
import { reportKeys, retryUnlessMissing } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useConnectivity } from '@/lib/connectivity'
import { toError } from '@/lib/errors'
import { connectionLoadingQuery, errorQuery, successQuery } from '@/model/queryStates'
import type { QueryState } from '@/model/types'

import { useAppActive } from '../handoff/useTaskRun'

export function useInboxStatus(enabled: boolean): QueryState<InboxStatusApi> {
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    const mode = useDataMode()
    const appActive = useAppActive()
    const offline = useConnectivity((state) => state.status === 'offline')
    const active = enabled && appActive && mode === 'live' && scope !== null
    const query = useQuery({
        queryKey: inboxStatusKey(scope),
        queryFn: ({ signal }) => {
            if (!scope) throw new Error('Choose a project to continue')
            return fetchInboxStatus(scope, signal)
        },
        enabled: active,
        retry: retryUnlessMissing,
        staleTime: 30_000,
        refetchOnMount: 'always',
        refetchInterval: (query) =>
            active && ['pending', 'running'].includes(query.state.data?.first_report_status ?? '') ? 15_000 : false,
    })
    const hasReport = !!query.data?.has_report_history || query.data?.first_report_status === 'report_created'
    useEffect(() => {
        if (active && hasReport) {
            void queryClient.invalidateQueries({ queryKey: reportKeys.inbox(scope), exact: true })
        }
    }, [active, hasReport, scope, queryClient])
    const wasActive = useRef(active)
    useEffect(() => {
        if (active && !wasActive.current) void query.refetch()
        wasActive.current = active
    }, [active, query.refetch])
    if (mode === 'demo')
        return successQuery({
            setup_state: 'active',
            has_report_history: true,
            first_report_status: null,
            can_configure: false,
        })
    if (query.data) return successQuery(query.data, { refetch: query.refetch, isRefetching: query.isFetching })
    if (query.isError) return errorQuery(toError(query.error), query.refetch)
    return connectionLoadingQuery(offline, query.refetch)
}
