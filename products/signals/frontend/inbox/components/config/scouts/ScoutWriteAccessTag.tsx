import { IconPencil } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { scoutWriteScopeLabels } from './scoutWriteScopes'

/**
 * Names what a scout may write in the project, or nothing for a read-only scout. Every other scout
 * reads the project, so a chip on those would label the norm and hide the exception in the noise.
 *
 * A dry run holds no grant, so the chip goes muted rather than away: the grant is still set and
 * comes back the moment the scout leaves dry run, and hiding it would make that a surprise.
 */
export function ScoutWriteAccessTag({
    writeScopes,
    emit = true,
    compact = false,
}: {
    writeScopes: readonly string[] | undefined
    /** The scout's `emit`. Off means a dry run, whose runs never hold the grant. */
    emit?: boolean
    /** Icon only, for a row too narrow to carry the labels. The tooltip still names them. */
    compact?: boolean
}): JSX.Element | null {
    const labels = scoutWriteScopeLabels(writeScopes)
    if (labels.length === 0) {
        return null
    }
    const objects = labels.join(', ').toLowerCase()
    const title = emit
        ? `This scout can write ${objects} in this project`
        : `Write access to ${objects} is set, but stays off while this scout is a dry run`
    return (
        <Tooltip title={title}>
            <LemonTag size="small" type={emit ? 'option' : 'muted'} icon={<IconPencil />}>
                {compact ? null : labels.join(', ')}
            </LemonTag>
        </Tooltip>
    )
}
