import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { Dashboard } from 'scenes/dashboard/Dashboard'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { teamLogic } from 'scenes/teamLogic'

import { homeDashboardChoiceLogic } from './homeDashboardChoiceLogic'
import { homeTabDashboardLogic, homeTabDashboardProps } from './homeTabDashboardLogic'
import { HomeTabDefault } from './HomeTabDefault'
import { HomeTabEmptyDashboard } from './HomeTabEmptyDashboard'

export function HomeTabDashboard({
    dashboardId,
    dashboardActions,
}: {
    dashboardId: number
    dashboardActions?: ReactNode
}): JSX.Element {
    const { dashboardMissing, dashboardEmpty } = useValues(homeTabDashboardLogic({ dashboardId }))
    const { currentTeamLoading } = useValues(teamLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { continueHomeDashboardWithAI, restorePostHogHome } = useActions(homeDashboardChoiceLogic)

    if (dashboardMissing) {
        return <HomeTabDefault dashboardActions={dashboardActions} />
    }
    if (dashboardEmpty) {
        return (
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
        )
    }
    const { id, placement, readOnly } = homeTabDashboardProps(dashboardId)
    return (
        <div className="-mt-8">
            <Dashboard id={String(id)} placement={placement} readOnly={readOnly} />
        </div>
    )
}
