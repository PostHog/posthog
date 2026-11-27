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
    // A browser clock behind the server's would show the request time of a settings check as a future time.
    const shownAsOf = dayjs(asOf).isAfter(dayjs()) ? dayjs() : asOf
    // `-mb-px` takes back the pixel of the time's dotted border, and `-top-px` lifts the clock level with the capitals.
    return (
        <span className={cn('flex items-center gap-1', className)}>
            {isOutOfDate && <IconClock className="relative -top-px" />}
            <span>Data up to</span>
            <TZLabel time={shownAsOf} className="-mb-px" />
        </span>
    )
}
