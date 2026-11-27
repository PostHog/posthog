import { IconClock } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

export function HealthCheckOutOfDateClock({ asOf }: { asOf: string }): JSX.Element {
    const label = `Data up to ${dayjs(asOf).fromNow()}`
    return (
        <Tooltip title={label}>
            <span className="flex text-sm text-secondary" role="img" aria-label={label}>
                <IconClock />
            </span>
        </Tooltip>
    )
}
