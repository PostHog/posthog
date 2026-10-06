import { useActions, useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { TodayBulkSelection } from '~/layout/today/TodaySessionBulkActionItems'
import { ownedBy } from '~/layout/today/todayWorkItems'

import { spaceFeedSelectionLogic } from './spaceFeedSelectionLogic'

export function useSpaceFeedBulkSelection(spaceId: string): TodayBulkSelection {
    const logic = spaceFeedSelectionLogic({ id: spaceId })
    const { selectedSessionIds, bulkPinDirection, bulkAction, runningSelectedCount, selectedSessions } =
        useValues(logic)
    const { user } = useValues(userLogic)
    const { pinSelected, fileSelectedTo, requestBulkArchive } = useActions(logic)
    return {
        spaceId,
        selectedSessionIds,
        ownsAllSelected: selectedSessions.every((item) => ownedBy(item, user?.id)),
        bulkPinDirection,
        bulkAction,
        runningSelectedCount,
        pinSelected,
        fileSelectedTo,
        requestBulkArchive,
    }
}
