import { useActions, useValues } from 'kea'

import { TodayBulkSelection } from '~/layout/today/TodaySessionBulkActionItems'

import { spaceFeedSelectionLogic } from './spaceFeedSelectionLogic'

export function useSpaceFeedBulkSelection(spaceId: string): TodayBulkSelection {
    const logic = spaceFeedSelectionLogic({ id: spaceId })
    const { selectedSessionIds, bulkPinDirection, bulkAction, runningSelectedCount } = useValues(logic)
    const { pinSelected, requestBulkArchive } = useActions(logic)
    return {
        selectedSessionIds,
        bulkPinDirection,
        bulkAction,
        runningSelectedCount,
        pinSelected,
        requestBulkArchive,
    }
}
