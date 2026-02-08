import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PRIORITY_TAG_TYPE, PRIORITY_TOOLTIP } from './constants'
import { ImmediateAction } from './types'

export interface ImmediateActionsSectionProps {
    actions: ImmediateAction[]
}

export function ImmediateActionsSection({ actions }: ImmediateActionsSectionProps): JSX.Element {
    const sortedActions = [...actions].sort((a, b) => {
        const order: Record<string, number> = { now: 0, soon: 1, later: 2 }
        return (order[a.priority] ?? 2) - (order[b.priority] ?? 2)
    })

    return (
        <div className="flex flex-col gap-2 p-2">
            {sortedActions.map((action, index) => (
                <div key={index} className="flex items-start gap-2 p-2 bg-bg-light rounded">
                    <Tooltip title={PRIORITY_TOOLTIP[action.priority]}>
                        <LemonTag type={PRIORITY_TAG_TYPE[action.priority] ?? 'muted'} size="small">
                            {action.priority.toUpperCase()}
                        </LemonTag>
                    </Tooltip>
                    <div className="flex flex-col gap-0.5">
                        <span className="text-sm font-medium">{action.action}</span>
                        <span className="text-xs text-muted">{action.why}</span>
                    </div>
                </div>
            ))}
        </div>
    )
}
