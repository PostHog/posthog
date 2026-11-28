import { useActions, useValues } from 'kea'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DashboardScoutListItem } from './DashboardScoutListItem'
import { DashboardScoutLogicProps, dashboardScoutLogic } from './dashboardScoutLogic'
import { DashboardScoutOffer } from './DashboardScoutOffer'

export function DashboardScoutSection(props: DashboardScoutLogicProps): JSX.Element | null {
    const logic = dashboardScoutLogic(props)
    const { dashboardScouts, scoutOffered } = useValues(logic)
    const { openSetup } = useActions(logic)
    // A scout is a skill plus its schedule, so creating one takes the same access as writing a skill.
    const createDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmSkill,
        AccessControlLevel.Editor
    )

    if (dashboardScouts === null) {
        return null
    }
    if (dashboardScouts.length > 0) {
        return (
            <div className="flex flex-col gap-2">
                {dashboardScouts.map((scout) => (
                    <DashboardScoutListItem key={scout.id} scout={scout} />
                ))}
            </div>
        )
    }
    return scoutOffered ? <DashboardScoutOffer onSetUp={openSetup} disabledReason={createDisabledReason} /> : null
}
