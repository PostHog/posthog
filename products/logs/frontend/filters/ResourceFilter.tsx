import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { logsLogic } from '../logsLogic'

export const ResourceFilter = (): JSX.Element => {
    const { resource } = useValues(logsLogic)
    const { setResource } = useActions(logsLogic)

    return (
        <span className="rounded bg-surface-primary">
            <LemonInput size="small" value={resource} onChange={setResource} placeholder="Resource" />
        </span>
    )
}
