import { useValues } from 'kea'

import {
    IconCheckCircle,
    IconCircleDashed,
    IconClockRewind,
    IconExternal,
    IconSpinner,
    IconWarning,
    IconX,
} from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { DetailSection } from './DetailSection'
import { CHECK_VARIANT_LABELS, CHECK_VARIANT_ORDER, CheckVariant, summarizePrChecks } from './prChecksPresentation'

const VARIANT_META: Record<CheckVariant, { icon: JSX.Element; iconClassName: string; summaryClassName: string }> = {
    failure: {
        icon: <IconWarning />,
        iconClassName: 'text-danger',
        summaryClassName: 'text-danger',
    },
    cancelled: {
        icon: <IconX />,
        iconClassName: 'text-muted',
        summaryClassName: 'text-secondary',
    },
    pending: {
        icon: <IconSpinner className="animate-spin motion-reduce:animate-none" />,
        iconClassName: 'text-warning',
        summaryClassName: 'text-warning',
    },
    stale: {
        icon: <IconClockRewind />,
        iconClassName: 'text-muted',
        summaryClassName: 'text-secondary',
    },
    success: {
        icon: <IconCheckCircle />,
        iconClassName: 'text-success',
        summaryClassName: 'text-success',
    },
    neutral: {
        icon: <IconCircleDashed />,
        iconClassName: 'text-muted',
        summaryClassName: 'text-tertiary',
    },
}

function CheckSummary({
    variant,
    count,
    compact,
}: {
    variant: CheckVariant
    count: number
    compact: boolean
}): JSX.Element | null {
    if (count === 0) {
        return null
    }

    const meta = VARIANT_META[variant]
    const variantLabel = CHECK_VARIANT_LABELS[variant].toLowerCase()
    const label = `${count} ${variantLabel}`
    return (
        <span
            className={`inline-flex items-center gap-1 whitespace-nowrap ${meta.summaryClassName}`}
            title={compact ? label : undefined}
        >
            <span aria-hidden className={`flex items-center [&_svg]:size-3 ${meta.iconClassName}`}>
                {meta.icon}
            </span>
            <span className="font-medium tabular-nums">{count}</span>
            <span className={compact ? 'sr-only' : undefined}>{variantLabel}</span>
        </span>
    )
}

function CheckSummaryList({
    counts,
    compact,
}: {
    counts: Record<CheckVariant, number>
    compact: boolean
}): JSX.Element {
    return (
        <span
            className={
                compact
                    ? 'inline-flex items-center gap-x-2.5 text-[0.6875rem]'
                    : 'flex w-full flex-wrap items-center gap-x-2.5 gap-y-1 text-[0.6875rem]'
            }
        >
            {CHECK_VARIANT_ORDER.map((variant) => (
                <CheckSummary key={variant} variant={variant} count={counts[variant]} compact={compact} />
            ))}
        </span>
    )
}

/**
 * "CI checks" section for a report's implementation PR: the GitHub Actions check runs and legacy
 * commit statuses of the PR's head commit, polled every 15s by `inboxReportDetailLogic` while the
 * detail is open (after repeated failures the poll backs off to a slow retry and the inline error
 * stays put until one succeeds). Read-only — each row links out to the check on GitHub.
 */
export function PrChecksSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { prChecks, prChecksLoading, prChecksError } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )

    // Never loaded yet: show a skeleton. Loaded-but-empty: nothing to show, so drop the section.
    if (prChecks === null) {
        if (!prChecksLoading && !prChecksError) {
            return null
        }
    } else if (prChecks.length === 0 && !prChecksError) {
        return null
    }

    const { sorted, counts } = summarizePrChecks(prChecks)

    return (
        <DetailSection
            icon={<IconCheckCircle />}
            title="CI checks"
            collapsible
            // `DetailSection` reads `defaultCollapsed` only on mount, so remount when an error appears
            // or clears. The header shows the per-status counts, so the list stays collapsed and does
            // not push the sections under it out of view. An error stays open so it is not hidden.
            key={prChecksError ? 'checks-error' : 'checks'}
            defaultCollapsed={!prChecksError}
            meta={
                sorted.length > 0 ? (open) => (open ? null : <CheckSummaryList counts={counts} compact />) : undefined
            }
            summary={
                sorted.length > 0
                    ? (open) => (open ? <CheckSummaryList counts={counts} compact={false} /> : null)
                    : undefined
            }
        >
            {prChecksError ? (
                <div className="rounded border border-danger bg-danger-highlight px-3 py-2.5 text-sm text-danger">
                    <span>{prChecksError.message}</span>
                    {prChecksError.remediationUrl ? (
                        <Link to={prChecksError.remediationUrl} className="ml-2">
                            Open GitHub integration settings
                        </Link>
                    ) : null}
                </div>
            ) : prChecks === null ? (
                <div className="overflow-hidden rounded border border-primary bg-surface-primary">
                    <LemonSkeleton className="h-10 w-full rounded-none" />
                    <LemonSkeleton className="h-10 w-full rounded-none border-t border-primary" />
                    <LemonSkeleton className="h-10 w-full rounded-none border-t border-primary" />
                </div>
            ) : (
                <ul className="m-0 max-h-96 overflow-y-auto rounded border border-primary bg-surface-primary p-0 list-none divide-y divide-border">
                    {sorted.map(({ check, variant }, i) => {
                        const meta = VARIANT_META[variant]
                        const row = (
                            <>
                                <span
                                    className={`flex shrink-0 items-center [&_svg]:size-[1.125rem] ${meta.iconClassName}`}
                                    aria-hidden
                                >
                                    {meta.icon}
                                </span>
                                <span
                                    className="min-w-0 flex-1 truncate text-sm font-medium text-primary"
                                    title={check.name}
                                >
                                    {check.name}
                                </span>
                                <span className="shrink-0 text-xs text-tertiary transition-colors group-hover:text-secondary">
                                    {CHECK_VARIANT_LABELS[variant]}
                                </span>
                                {check.url && (
                                    <IconExternal className="size-3.5 shrink-0 text-tertiary opacity-60 transition-opacity group-hover:opacity-100" />
                                )}
                            </>
                        )
                        return (
                            <li key={`${check.name}-${i}`}>
                                {check.url ? (
                                    <Link
                                        to={check.url}
                                        target="_blank"
                                        className="group flex min-w-0 items-center gap-2.5 px-3 py-2.5 text-primary no-underline transition-colors hover:bg-fill-highlight-50 hover:text-primary focus-visible:bg-fill-highlight-50"
                                    >
                                        {row}
                                    </Link>
                                ) : (
                                    <span className="group flex min-w-0 items-center gap-2.5 px-3 py-2.5">{row}</span>
                                )}
                            </li>
                        )
                    })}
                </ul>
            )}
        </DetailSection>
    )
}
