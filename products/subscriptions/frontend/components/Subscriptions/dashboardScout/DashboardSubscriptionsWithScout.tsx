import { useValues } from 'kea'

import { TabbedManageSubscriptions, TabbedManageSubscriptionsProps } from '../views/TabbedManageSubscriptions'
import { dashboardScoutLogic } from './dashboardScoutLogic'
import { DashboardScoutSection } from './DashboardScoutSection'
import { DashboardScoutSetupForm } from './DashboardScoutSetupForm'

export interface DashboardSubscriptionsWithScoutProps extends Omit<TabbedManageSubscriptionsProps, 'resourceExtra'> {
    dashboardId: number
    dashboardName: string
}

export function DashboardSubscriptionsWithScout({
    dashboardName,
    ...listProps
}: DashboardSubscriptionsWithScoutProps): JSX.Element {
    const scoutProps = { dashboardId: listProps.dashboardId, dashboardName }
    const { setupOpen } = useValues(dashboardScoutLogic(scoutProps))

    if (setupOpen) {
        return <DashboardScoutSetupForm {...scoutProps} />
    }
    return <TabbedManageSubscriptions {...listProps} resourceExtra={<DashboardScoutSection {...scoutProps} />} />
}
