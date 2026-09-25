import clsx from 'clsx'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import type { ReputationAction } from './reputationActions'
import { SEVERITY_STYLE } from './reputationUtils'

export function ReputationActionRow({ action, position }: { action: ReputationAction; position: number }): JSX.Element {
    const severity = SEVERITY_STYLE[action.severity]
    return (
        <li
            className={clsx(
                'flex flex-col gap-3 px-4 py-3 border-b border-l-4 last:border-b-0 @xl:flex-row @xl:items-center',
                severity.border
            )}
            data-attr="workflows-reputation-action"
        >
            <div className="flex gap-3 flex-1 min-w-0">
                <span className="text-secondary tabular-nums w-5 shrink-0" aria-hidden>
                    {position}
                </span>
                <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="font-semibold break-words">{action.title}</span>
                        <LemonTag type={severity.tagType} size="small">
                            {severity.label}
                        </LemonTag>
                    </div>
                    <p className="text-secondary mb-0 mt-1">{action.description}</p>
                </div>
            </div>
            <div className="flex flex-wrap gap-2 shrink-0 pl-8 @xl:pl-0">
                <LemonButton
                    type="primary"
                    size="small"
                    to={action.primary.to}
                    targetBlank={action.primary.external}
                    sideIcon={action.primary.external ? undefined : <IconArrowRight />}
                    data-attr={`workflows-reputation-action-${action.kind}-primary`}
                >
                    {action.primary.label}
                </LemonButton>
                {action.secondary && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={action.secondary.to}
                        targetBlank={action.secondary.external}
                        data-attr={`workflows-reputation-action-${action.kind}-secondary`}
                    >
                        {action.secondary.label}
                    </LemonButton>
                )}
            </div>
        </li>
    )
}
