import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { Dashboard } from 'scenes/dashboard/Dashboard'

import { homeTabDashboardLogic, homeTabDashboardProps } from './homeTabDashboardLogic'
import { HomeTabDefault } from './HomeTabDefault'

export function HomeTabDashboard({
    dashboardId,
    dashboardActions,
}: {
    dashboardId: number
    dashboardActions?: ReactNode
}): JSX.Element {
    const { dashboardMissing } = useValues(homeTabDashboardLogic({ dashboardId }))

    if (dashboardMissing) {
        return <HomeTabDefault dashboardActions={dashboardActions} />
    }
    const { id, placement, readOnly } = homeTabDashboardProps(dashboardId)
    return (
        <div className="-mt-8">
            <Dashboard id={String(id)} placement={placement} readOnly={readOnly} />
        </div>
    )
}
