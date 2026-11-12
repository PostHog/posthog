import { useValues } from 'kea'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import { BreakdownType, GroupTypeIndex } from '~/types'

import { isAllCohort, isCohort } from './taxonomicBreakdownFilterUtils'

export function useBreakdownPropertyName(
    breakdown: string | number,
    breakdownType: BreakdownType | null | undefined
): string | number {
    const { cohortsById } = useValues(cohortsModel)
    const { groupTypes } = useValues(groupsModel)

    if (isAllCohort(breakdown)) {
        return 'All Users'
    }
    if (isCohort(breakdown)) {
        return cohortsById[breakdown]?.name || `Cohort ${breakdown}`
    }
    if (breakdownType === 'event_metadata' && (breakdown as string).startsWith('$group_')) {
        const group = groupTypes.get(
            parseInt((breakdown as string).replace('$group_', '')) as unknown as GroupTypeIndex
        )
        return group ? group.name_singular || group.group_type : breakdown
    }
    return extractDisplayLabel(breakdown as string)
}
