import { IconPullRequest } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { scoutReportActionLabels } from './scoutReportActions'

/**
 * Names the report actions a scout may start, or nothing for a scout that holds none, which is the
 * default. A dry run holds no grant, so the chip goes muted rather than away, like write access.
 */
export function ScoutReportActionsTag({
    reportActions,
    emit = true,
}: {
    reportActions: readonly string[] | undefined
    /** The scout's `emit`. Off means a dry run, whose runs never hold the grant. */
    emit?: boolean
}): JSX.Element | null {
    const labels = scoutReportActionLabels(reportActions)
    if (labels.length === 0) {
        return null
    }
    const actions = labels.join(', ').toLowerCase()
    const title = emit
        ? `This scout can start ${actions} on report pull requests, acting as the person its runs act as`
        : `This scout is granted ${actions}, but holds none while it is a dry run`
    return (
        <Tooltip title={title}>
            <LemonTag size="small" type={emit ? 'option' : 'muted'} icon={<IconPullRequest />} wrap>
                {labels.join(', ')}
            </LemonTag>
        </Tooltip>
    )
}
