import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

export function CIDataAsOfLabel({ asOf }: { asOf: string }): JSX.Element {
    return (
        <Tooltip title="CI data on this page is at least this fresh. Refresh reloads it and does not start a sync.">
            <span className="self-center text-xs text-secondary">
                Updated <TZLabel time={asOf} />
            </span>
        </Tooltip>
    )
}
