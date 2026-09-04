import { IconPencil } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { scoutWriteScopeLabels } from './scoutWriteScopes'

/**
 * Names what a scout may write in the project, or nothing for a read-only scout. Every other scout
 * reads the project, so a chip on those would label the norm and hide the exception in the noise.
 */
export function ScoutWriteAccessTag({
    writeScopes,
}: {
    writeScopes: readonly string[] | undefined
}): JSX.Element | null {
    const labels = scoutWriteScopeLabels(writeScopes)
    if (labels.length === 0) {
        return null
    }
    return (
        <Tooltip title={`This scout can write ${labels.join(', ').toLowerCase()} in this project`}>
            <LemonTag size="small" type="option" icon={<IconPencil />}>
                {labels.join(', ')}
            </LemonTag>
        </Tooltip>
    )
}
