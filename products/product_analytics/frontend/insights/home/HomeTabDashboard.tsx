import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { Dashboard } from 'scenes/dashboard/Dashboard'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { teamLogic } from 'scenes/teamLogic'

import { homeDashboardChoiceLogic } from './homeDashboardChoiceLogic'
import { homeTabDashboardLogic, homeTabDashboardProps } from './homeTabDashboardLogic'
import { HomeTabDefault } from './HomeTabDefault'
import { HomeTabEmptyDashboard } from './HomeTabEmptyDashboard'

export interface HomeTabPage {
    /** The page title, shown when Home does not show the full dashboard. */
    title: JSX.Element
    /** Controls added to the dashboard header when the full dashboard is the page. */
    dashboardHeaderActions: JSX.Element
}

export function HomeTabDashboard({
    dashboardId,
    dashboardActions,
    page,
}: {
    dashboardId: number
    dashboardActions?: ReactNode
    page?: HomeTabPage
}): JSX.Element {
    const display = page ? 'page' : 'embedded'
    const { dashboardMissing, dashboardEmpty } = useValues(homeTabDashboardLogic({ dashboardId, display }))
    const { currentTeamLoading } = useValues(teamLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { continueHomeDashboardWithAI, restorePostHogHome } = useActions(homeDashboardChoiceLogic)

    if (dashboardMissing) {
        return (
            <>
                {page?.title}
                <HomeTabDefault dashboardActions={dashboardActions} />
            </>
        )
    }
    if (dashboardEmpty) {
        return (
            <>
                {page?.title}
                <div className="py-3">
                    <HomeTabEmptyDashboard
                        onContinueWithAI={() => continueHomeDashboardWithAI(dashboardId)}
                        onResetToDefault={restorePostHogHome}
                        resetting={currentTeamLoading}
                        aiDisabledReason={
                            !dataProcessingAccepted &&
                            (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')
                        }
                    />
                </div>
            </>
        )
    }
    const { id, placement, readOnly } = homeTabDashboardProps(dashboardId, display)
    if (page) {
        return (
            <Dashboard
                id={String(id)}
                placement={placement}
                readOnly={readOnly}
                headerActions={page.dashboardHeaderActions}
            />
        )
    }
    return (
        <div className="-mt-8">
            <Dashboard id={String(id)} placement={placement} readOnly={readOnly} />
        </div>
    )
}
