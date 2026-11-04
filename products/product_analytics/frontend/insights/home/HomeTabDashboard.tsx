import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { Dashboard } from 'scenes/dashboard/Dashboard'
import { DASHBOARD_CANNOT_EDIT_MESSAGE, insightIsAddedToDashboard } from 'scenes/dashboard/DashboardHeader'
import { DashboardLoadAction } from 'scenes/dashboard/dashboardLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

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
    const logic = homeTabDashboardLogic({ dashboardId, display })
    const { dashboardMissing, dashboardEmpty, canEditDashboard } = useValues(logic)
    const { loadDashboard } = useActions(logic)
    const { currentTeamLoading } = useValues(teamLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { continueHomeDashboardWithAI, restorePostHogHome } = useActions(homeDashboardChoiceLogic)

    // A running AI response delivers only to the listener it claimed at send time. One listener for both the
    // empty state and the dashboard keeps that claim when the first chart replaces the empty state.
    useMcpToolApplyBack({
        tools: ['insight-create', 'insight-update'],
        targetKey: `dashboard:${dashboardId}`,
        active: !dashboardMissing && canEditDashboard,
        onApply: (_event, { innerInput }) => {
            if (insightIsAddedToDashboard(innerInput, dashboardId)) {
                loadDashboard({ action: DashboardLoadAction.Update })
            }
        },
    })

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
                            !canEditDashboard
                                ? DASHBOARD_CANNOT_EDIT_MESSAGE
                                : !dataProcessingAccepted &&
                                  (dataProcessingApprovalDisabledReason ??
                                      'Approve AI data processing to use PostHog AI')
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
                compact
                parentReloadsOnAIChanges
            />
        )
    }
    return (
        <div className="-mt-8">
            <Dashboard id={String(id)} placement={placement} readOnly={readOnly} parentReloadsOnAIChanges />
        </div>
    )
}
