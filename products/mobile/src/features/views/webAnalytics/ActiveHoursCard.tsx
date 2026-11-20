import { type ReactElement, useCallback } from 'react'

import { formatClock } from '@/lib/dates'
import { useClockPreference } from '@/lib/useClockPreference'
import { plural } from '@/model/adapters/text'
import type { WebActiveHoursSnapshot } from '@/model/views'
import { HeatGrid } from '@/ui/chart/HeatGrid'

import { useWebItemData, type WebItemRef } from './hooks'
import { WebCard, webCardState } from './WebCard'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
const MARKED_HOURS = [0, 6, 12, 18] as const

function hourLabel(hour: number, uses24hourClock: boolean): string {
    if (uses24hourClock) {
        return String(hour).padStart(2, '0')
    }
    const hour12 = hour % 12 === 0 ? 12 : hour % 12
    return `${hour12} ${hour < 12 ? 'AM' : 'PM'}`
}

export function ActiveHoursCard({ data }: { data: WebItemRef }): ReactElement {
    const uses24hourClock = useClockPreference()
    const item = useWebItemData<WebActiveHoursSnapshot>(data)
    const snapshot = item.snapshot
    const hasContent = Boolean(snapshot?.cells.some((row) => row.some((value) => value > 0)))
    const describe = useCallback(
        (row: number, column: number, value: number) =>
            `${WEEKDAYS[row] ?? ''} ${formatClock(new Date(2000, 0, 3, column), uses24hourClock)} · ${plural(value, 'visitor')}`,
        [uses24hourClock]
    )
    return (
        <WebCard
            title="Active hours"
            meta={['Visitors by hour', snapshot?.timezone].filter(Boolean).join(' · ')}
            state={webCardState(item, hasContent)}
            error={item.error}
            stale={snapshot?.refreshFailed ?? false}
            updating={item.updating}
            loadingHeight={160}
            testID="web-active-hours"
        >
            {snapshot ? (
                <HeatGrid
                    cells={snapshot.cells}
                    rowLabels={WEEKDAYS}
                    columnMarks={MARKED_HOURS.map((hour) => [hour, hourLabel(hour, uses24hourClock)] as const)}
                    describe={describe}
                    label="Active hours, visitors by weekday and hour"
                    selectionId="web-active-hours"
                    testID="web-active-hours-grid"
                />
            ) : null}
        </WebCard>
    )
}
