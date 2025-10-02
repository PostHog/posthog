import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers } from 'kea'

import { issueActionsLogic } from '../components/IssueActions/issueActionsLogic'
import type { bulkSelectLogicType } from './bulkSelectLogicType'

export const bulkSelectLogic = kea<bulkSelectLogicType>([
    path(['products', 'error_tracking', 'logics', 'bulkSelectLogic']),

    connect(() => ({
        actions: [issueActionsLogic, ['mutationSuccess', 'mutationFailure']],
    })),

    actions({
        setSelectedIssueIds: (ids: string[]) => ({ ids }),
        setShiftKeyHeld: (shiftKeyHeld: boolean) => ({ shiftKeyHeld }),
        setPreviouslyCheckedRecordIndex: (index: number) => ({ index }),
    }),

    reducers({
        selectedIssueIds: [
            [] as string[],
            {
                setSelectedIssueIds: (_, { ids }) => ids,
            },
        ],
        shiftKeyHeld: [
            false as boolean,
            {
                setShiftKeyHeld: (_, { shiftKeyHeld }) => shiftKeyHeld,
            },
        ],
        previouslyCheckedRecordIndex: [
            null as number | null,
            {
                setPreviouslyCheckedRecordIndex: (_, { index }) => index,
            },
        ],
    }),

    listeners(({ actions }) => ({
        mutationSuccess: () => actions.setSelectedIssueIds([]),
        mutationFailure: () => actions.setSelectedIssueIds([]),
    })),

    afterMount(({ actions, cache }) => {
        const onKeyChange = (event: KeyboardEvent): void => {
            actions.setShiftKeyHeld(event.shiftKey)
        }

        // register shift key listener
        window.addEventListener('keydown', onKeyChange)
        window.addEventListener('keyup', onKeyChange)
        cache.onKeyChange = onKeyChange
    }),
    beforeUnmount(({ cache }) => {
        // unregister shift key listener
        window.removeEventListener('keydown', cache.onKeyChange)
        window.removeEventListener('keyup', cache.onKeyChange)
    }),
])
