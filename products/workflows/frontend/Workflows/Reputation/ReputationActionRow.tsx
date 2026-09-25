import clsx from 'clsx'

import { IconArrowRight, IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import type { ReputationAction, ReputationActionSeverity } from './reputationActions'

const SEVERITY_TAG: Record<ReputationActionSeverity, { label: string; type: LemonTagType }> = {
    high: { label: 'Fix now', type: 'danger' },
    medium: { label: 'Needs attention', type: 'warning' },
    low: { label: 'Worth a look', type: 'muted' },
}

const SEVERITY_BORDER: Record<ReputationActionSeverity, string> = {
    high: 'border-l-danger',
    medium: 'border-l-warning',
    low: 'border-l-muted',
}

export function ReputationActionRow({ action, position }: { action: ReputationAction; position: number }): JSX.Element {
    return (
        <li
            className={clsx(
                'flex flex-col gap-3 px-4 py-3 border-b border-l-4 last:border-b-0 @xl:flex-row @xl:items-center',
                SEVERITY_BORDER[action.severity]
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
                        <LemonTag type={SEVERITY_TAG[action.severity].type} size="small">
                            {SEVERITY_TAG[action.severity].label}
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
                    sideIcon={action.primary.external ? <IconExternal /> : <IconArrowRight />}
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
                        sideIcon={action.secondary.external ? <IconExternal /> : undefined}
                        data-attr={`workflows-reputation-action-${action.kind}-secondary`}
                    >
                        {action.secondary.label}
                    </LemonButton>
                )}
            </div>
        </li>
    )
}
