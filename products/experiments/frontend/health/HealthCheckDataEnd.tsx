import { IconClock } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

export function HealthCheckDataEnd({
    asOf,
    isOutOfDate,
    className,
}: {
    asOf: string
    isOutOfDate: boolean
    className?: string
}): JSX.Element {
    // A check that reads only settings gets the server's request time. A browser clock that runs behind the server
    // would show that time as one in the future.
    const shownAsOf = dayjs(asOf).isAfter(dayjs()) ? dayjs() : asOf
    return (
        <span className={cn('flex items-center gap-1', className)}>
            {isOutOfDate && <IconClock />}
            <span>Data up to</span>
            <TZLabel time={shownAsOf} />
        </span>
    )
}
