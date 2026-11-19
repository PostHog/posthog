import clsx from 'clsx'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ImpactStep, stepBarPercents } from './impactSteps'

export function ImpactFunnel({ steps }: { steps: ImpactStep[] }): JSX.Element {
    const barPercents = stepBarPercents(steps)
    return (
        <ol className="m-0 p-0 list-none grid grid-cols-6 gap-2" data-attr="email-impact-funnel">
            {steps.map((step, index) => (
                <li key={step.key} className="flex flex-col gap-1 min-w-0">
                    <StepBar step={step} percent={barPercents[index]} />
                    <span className="text-xs text-secondary truncate" title={step.label}>
                        {step.label}
                    </span>
                    <StepValue step={step} />
                    <StepShare step={step} />
                </li>
            ))}
        </ol>
    )
}

function StepBar({ step, percent }: { step: ImpactStep; percent: number | null }): JSX.Element {
    return (
        <div className="h-28 rounded bg-surface-secondary flex items-end overflow-hidden">
            {percent !== null && percent > 0 && (
                <div
                    data-attr={`email-impact-bar-${step.key}`}
                    className={step.key === 'converted' ? 'w-full bg-success' : 'w-full bg-accent'}
                    style={{ height: `${percent}%` }}
                />
            )}
        </div>
    )
}

function StepValue({ step }: { step: ImpactStep }): JSX.Element {
    if (step.value !== null) {
        return <span className="font-semibold text-base">{humanFriendlyNumber(step.value)}</span>
    }
    if (step.missingFixedByLinkTagging) {
        return (
            <Tooltip title={step.missingDetail}>
                <Link
                    className="text-xs"
                    to={urls.settings('environment-workflows', 'workflows-email-run-link-tag')}
                    target="_blank"
                    data-attr="email-impact-link-tagging-settings-link"
                >
                    {step.missing}
                </Link>
            </Tooltip>
        )
    }
    return (
        <Explained detail={step.missingDetail} className="text-xs text-secondary">
            {step.missing}
        </Explained>
    )
}

function StepShare({ step }: { step: ImpactStep }): JSX.Element | null {
    if (step.share === null) {
        return null
    }
    return (
        <span className="text-xs text-secondary">
            <span>{percentage(step.share, 1)}</span>
            {step.shareOf && <Explained detail={step.shareDetail}>{` of ${step.shareOf}`}</Explained>}
        </span>
    )
}

function Explained({
    detail,
    className,
    children,
}: {
    detail?: string
    className?: string
    children: React.ReactNode
}): JSX.Element {
    if (!detail) {
        return <span className={className}>{children}</span>
    }
    return (
        <Tooltip title={detail}>
            <span tabIndex={0} className={clsx(className, 'underline decoration-dotted cursor-help')}>
                {children}
            </span>
        </Tooltip>
    )
}
