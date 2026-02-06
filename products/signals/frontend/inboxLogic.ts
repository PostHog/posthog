import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { signalReportsList } from './generated/api'
import { SignalReportApi } from './generated/api.schemas'
import type { inboxLogicType } from './inboxLogicType'

export type InboxTab = 'active' | 'dismissed'

export const inboxLogic = kea<inboxLogicType>([
    path(['products', 'signals', 'frontend', 'inboxLogic']),

    actions({
        setActiveTab: (tab: InboxTab) => ({ tab }),
        dismissReport: (reportId: string) => ({ reportId }),
        undoDismissReport: (reportId: string) => ({ reportId }),
        setSelectedReportId: (reportId: string | null) => ({ reportId }),
    }),

    reducers({
        activeTab: [
            'active' as InboxTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        dismissedReportIds: [
            [] as string[],
            {
                dismissReport: (state, { reportId }) => [...state, reportId],
                undoDismissReport: (state, { reportId }) => state.filter((id) => id !== reportId),
            },
        ],
        selectedReportId: [
            null as string | null,
            {
                setSelectedReportId: (_, { reportId }) => reportId,
            },
        ],
    }),

    loaders({
        reports: [
            [] as SignalReportApi[],
            {
                loadReports: async () => {
                    const projectId = String(teamLogic.values.currentTeamId)
                    const response = await signalReportsList(projectId, { limit: 100 })
                    return response.results
                },
            },
        ],
    }),

    selectors({
        activeReports: [
            (s) => [s.reports, s.dismissedReportIds],
            (reports, dismissedIds): SignalReportApi[] => reports.filter((r) => !dismissedIds.includes(r.id)),
        ],
        dismissedReports: [
            (s) => [s.reports, s.dismissedReportIds],
            (reports, dismissedIds): SignalReportApi[] => reports.filter((r) => dismissedIds.includes(r.id)),
        ],
        visibleReports: [
            (s) => [s.activeTab, s.activeReports, s.dismissedReports],
            (tab, active, dismissed): SignalReportApi[] => (tab === 'active' ? active : dismissed),
        ],
        selectedReport: [
            (s) => [s.reports, s.selectedReportId],
            (reports, id): SignalReportApi | null => reports.find((r) => r.id === id) ?? null,
        ],
        reportCount: [(s) => [s.activeReports], (reports): number => reports.length],
    }),

    listeners(({ values, actions }) => ({
        loadReportsSuccess: () => {
            // Auto-select the first report if none is selected
            if (!values.selectedReportId && values.visibleReports.length > 0) {
                actions.setSelectedReportId(values.visibleReports[0].id)
            }
        },
        setActiveTab: () => {
            // Select first report in new tab
            if (values.visibleReports.length > 0) {
                actions.setSelectedReportId(values.visibleReports[0].id)
            } else {
                actions.setSelectedReportId(null)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadReports()
    }),
])
