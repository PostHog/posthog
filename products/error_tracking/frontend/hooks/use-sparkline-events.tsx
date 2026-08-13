import { useValues } from 'kea'
import { useMemo } from 'react'

import { ErrorEventType } from 'lib/components/Errors/types'
import { Dayjs } from 'lib/dayjs'

import type { SparklineEvent } from '../components/VolumeSparkline/types'
import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

export function useSparklineEvents(): SparklineEvent<string>[] {
    const { firstSeen, lastSeen, selectedEvent } = useValues(errorTrackingIssueSceneLogic)

    return useMemo(() => {
        const events = []
        if (firstSeen) {
            events.push({
                id: 'first_seen',
                date: firstSeen.toDate(),
                color: 'var(--brand-blue)',
                payload: 'First Seen',
            })
        }
        if (selectedEvent && !isFirstOrLastEvent(firstSeen, lastSeen, selectedEvent)) {
            events.push({
                id: 'current',
                date: new Date(selectedEvent.timestamp),
                color: 'var(--brand-yellow)',
                payload: 'Current',
            })
        }
        if (lastSeen) {
            events.push({
                id: 'last_seen',
                date: lastSeen.toDate(),
                color: 'var(--brand-red)',
                payload: 'Last Seen',
            })
        }
        return events
    }, [firstSeen, lastSeen, selectedEvent])
}

function isFirstOrLastEvent(
    firstSeen: Dayjs | null,
    lastSeen: Dayjs | null,
    selectedEvent: ErrorEventType | null
): boolean {
    if (selectedEvent && firstSeen?.isSame(selectedEvent.timestamp)) {
        return true
    }
    if (selectedEvent && lastSeen?.isSame(selectedEvent.timestamp)) {
        return true
    }
    return false
}
