import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { QualityChange } from './qualityChange'

export function QualityChangeMarker({ change }: { change: QualityChange | null }): JSX.Element | null {
    if (!change) {
        return null
    }
    const Icon = change.worse ? IconArrowUp : IconArrowDown
    const description = `${change.worse ? 'Up' : 'Down'} ${change.label} from ${change.previous} in the previous period`
    return (
        <Tooltip title={`Was ${change.previous} in the previous period`}>
            <span
                tabIndex={0}
                aria-label={description}
                className={`ml-1 inline-flex items-center gap-0.5 text-xs tabular-nums ${change.worse ? 'text-danger' : 'text-success'}`}
            >
                <Icon />
                {change.label}
            </span>
        </Tooltip>
    )
}
