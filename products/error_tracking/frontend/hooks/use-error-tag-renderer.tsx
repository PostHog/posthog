import { useValues } from 'kea'
import { ErrorEventType } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'
import { useCallback } from 'react'

import { ErrorTag } from '../components/ErrorTag'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

export function useErrorTagRenderer(): (evt: ErrorEventType | null) => JSX.Element {
    const { lastSeen, firstSeen, selectedEvent } = useValues(errorTrackingIssueSceneLogic)
    return useCallback(
        (evt: ErrorEventType | null) => {
            if (!evt) {
                return <></>
            }
            if (lastSeen && evt.timestamp && dayjs(evt.timestamp).isSame(lastSeen)) {
                return <ErrorTag color="red" label="Last Seen" />
            }
            if (firstSeen && evt.timestamp && dayjs(evt.timestamp).isSame(firstSeen)) {
                return <ErrorTag color="blue" label="First Seen" />
            }
            if (selectedEvent && selectedEvent.uuid == evt.uuid) {
                return <ErrorTag color="yellow" label="Current" />
            }
            return <></>
        },
        [lastSeen, firstSeen, selectedEvent]
    )
}
