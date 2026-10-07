import { LemonTag } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function OrphanTraceTag(): JSX.Element {
    return (
        <Tooltip title="Parent span not found">
            <LemonTag type="muted" size="small" data-attr="tracing-orphan-trace-tag">
                orphan
            </LemonTag>
        </Tooltip>
    )
}
