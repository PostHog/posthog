import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { Dashboard } from 'scenes/dashboard/Dashboard'

import { DashboardPlacement } from '~/types'

import { mcpAnalyticsDashboardLogic } from './mcpAnalyticsDashboardLogic'

export function MCPAnalyticsDashboard(): JSX.Element {
    const { selectedDashboardId, availableDashboardsLoading } = useValues(mcpAnalyticsDashboardLogic)

    if (availableDashboardsLoading || !selectedDashboardId) {
        return (
            <div className="text-center p-8">
                <Spinner captureTime />
            </div>
        )
    }

    return <Dashboard id={selectedDashboardId.toString()} placement={DashboardPlacement.Builtin} />
}
