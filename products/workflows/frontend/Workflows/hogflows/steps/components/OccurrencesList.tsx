import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

const VISIBLE_HEAD = 4
const VISIBLE_TAIL = 1

export function OccurrencesList({ occurrences, isFinite }: { occurrences: Date[]; isFinite: boolean }): JSX.Element {
    const now = new Date()
    const futureOccurrences = occurrences.filter((date) => date > now)
    const total = futureOccurrences.length
    const needsCollapse = isFinite && total > VISIBLE_HEAD + VISIBLE_TAIL + 1
    const lastIndex = total - 1

    const renderRow = (date: Date, i: number): JSX.Element => {
        const isFirst = i === 0
        const isLast = isFinite && i === lastIndex

        return (
            <div key={i} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                    <span
                        className={`w-2 h-2 rounded-full shrink-0 ${
                            isFirst ? 'bg-warning' : isLast ? 'bg-danger' : 'bg-border'
                        }`}
                    />
                    <span className={isFirst || isLast ? 'font-semibold' : 'text-muted'}>
                        {dayjs(date).utc().format('dddd, MMMM D YYYY · h:mm A')}
                    </span>
                </div>
                {isFirst && (
                    <LemonTag type="warning" size="small">
                        next
                    </LemonTag>
                )}
                {isLast && !isFirst && (
                    <LemonTag type="danger" size="small">
                        last
                    </LemonTag>
                )}
            </div>
        )
    }

    if (futureOccurrences.length === 0) {
        return <div className="text-xs text-muted italic">No upcoming occurrences</div>
    }

    if (needsCollapse) {
        const head = futureOccurrences.slice(0, VISIBLE_HEAD)
        const tail = futureOccurrences.slice(-VISIBLE_TAIL)
        const hiddenCount = total - VISIBLE_HEAD - VISIBLE_TAIL

        return (
            <>
                {head.map((date, i) => renderRow(date, i))}
                <div className="text-xs text-muted italic pl-4">
                    ...{hiddenCount} more occurrence{hiddenCount > 1 ? 's' : ''}...
                </div>
                {tail.map((date, i) => renderRow(date, total - VISIBLE_TAIL + i))}
            </>
        )
    }

    return (
        <>
            {futureOccurrences.map((date, i) => renderRow(date, i))}
            {!isFinite && <div className="text-xs text-muted italic pl-4">...continues indefinitely</div>}
        </>
    )
}
