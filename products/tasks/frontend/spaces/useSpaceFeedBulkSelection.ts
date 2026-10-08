import { useActions, useValues } from 'kea'

import { TodayBulkSelection } from '~/layout/today/TodaySessionBulkActionItems'

import { spaceFeedSelectionLogic } from './spaceFeedSelectionLogic'

export function useSpaceFeedBulkSelection(spaceId: string): TodayBulkSelection {
    const logic = spaceFeedSelectionLogic({ id: spaceId })
    const { selectedSessionIds, bulkPinDirection, bulkAction, runningSelectedCount } = useValues(logic)
    const { pinSelected, fileSelectedTo, requestBulkArchive } = useActions(logic)
    return {
        spaceId,
        selectedSessionIds,
        bulkPinDirection,
        bulkAction,
        runningSelectedCount,
        pinSelected,
        fileSelectedTo,
        requestBulkArchive,
    }
}
