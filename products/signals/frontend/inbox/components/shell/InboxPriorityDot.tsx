import { PRIORITY_ACCENT } from '../../filterOptions'
import { SignalReportPriority } from '../../types'

/** The colored dot that leads a priority option in the toolbar's priority filter. */
export function InboxPriorityDot({ priority }: { priority: SignalReportPriority }): JSX.Element {
    return (
        <span
            className="size-2 shrink-0 rounded-full"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ backgroundColor: PRIORITY_ACCENT[priority] }}
        />
    )
}
