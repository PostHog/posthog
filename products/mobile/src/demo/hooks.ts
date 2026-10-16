import { useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { errorQuery, successQuery } from '@/model/queryStates'
import type { ChatListItem, InboxItem, QueryState, ReportView } from '@/model/types'

import { buildDemoChatList } from './chats'
import { useDemoMode } from './demoMode'
import { type DemoView, deriveDemoInbox, deriveDemoReport } from './derive'
import { buildDemoFixtures, type DemoFixtures } from './fixtures'

function useDemoView(): DemoView {
    return useDemoMode(
        useShallow((state) => ({
            handed: state.handed,
            decisions: state.decisions,
            snoozed: state.snoozed,
            closed: state.closed,
            read: state.read,
            reviewers: state.reviewers,
            priorities: state.priorities,
            log: state.log,
        }))
    )
}

export function useDemoFixtures(): DemoFixtures {
    const anchor = useDemoMode((state) => state.anchor)
    return useMemo(() => buildDemoFixtures(new Date(anchor)), [anchor])
}

export function useDemoInboxQuery(): QueryState<InboxItem[]> {
    const fixtures = useDemoFixtures()
    const view = useDemoView()
    const isRefreshing = useDemoMode((state) => state.isRefreshing)
    const refresh = useDemoMode((state) => state.refresh)
    const items = useMemo(() => deriveDemoInbox(view, fixtures), [view, fixtures])
    return successQuery(items, { isRefetching: isRefreshing, refetch: refresh })
}

export function useDemoReportQuery(reportId: string): QueryState<ReportView> {
    const fixtures = useDemoFixtures()
    const view = useDemoView()
    const isRefreshing = useDemoMode((state) => state.isRefreshing)
    const refresh = useDemoMode((state) => state.refresh)
    const fixture = fixtures.byId[reportId]
    const report = useMemo(() => (fixture ? deriveDemoReport(view, fixture) : undefined), [view, fixture])
    if (!report) {
        return errorQuery(
            new Error("This report isn't in the demo. Go back to the inbox and pick another one."),
            refresh
        )
    }
    return successQuery(report, { isRefetching: isRefreshing, refetch: refresh })
}

export function useDemoChatsQuery(): QueryState<ChatListItem[]> {
    const anchor = useDemoMode((state) => state.anchor)
    const isRefreshing = useDemoMode((state) => state.isRefreshing)
    const refresh = useDemoMode((state) => state.refresh)
    const archivedChats = useDemoMode((state) => state.archivedChats)
    const items = useMemo(
        () => buildDemoChatList(new Date(anchor)).filter((item) => !archivedChats[item.sourceId]),
        [anchor, archivedChats]
    )
    return successQuery(items, { isRefetching: isRefreshing, refetch: refresh })
}
