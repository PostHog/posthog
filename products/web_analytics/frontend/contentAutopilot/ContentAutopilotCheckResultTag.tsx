import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { positionLabel } from './promptReport'

export const ContentAutopilotCheckResultTag = ({
    cited,
    checkFailed,
    position,
}: {
    cited: boolean
    checkFailed: boolean
    position?: number | null
}): JSX.Element =>
    checkFailed ? (
        <LemonTag type="danger">Failed</LemonTag>
    ) : cited ? (
        <Tooltip title={position ? `Your site is source ${position} in this answer` : undefined}>
            <LemonTag type="success">{position ? `Cited ${positionLabel(position)}` : 'Cited'}</LemonTag>
        </Tooltip>
    ) : (
        <LemonTag type="warning">Not cited</LemonTag>
    )
