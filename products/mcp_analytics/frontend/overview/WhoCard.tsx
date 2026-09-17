import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { Card, CardContent, CardHeader, CardTitle } from '@posthog/quill-primitives'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'

import { formatNumber } from '../dashboard/formatters'
import { HarnessLogo } from '../dashboard/harness'
import { mcpOverviewLogic } from './mcpOverviewLogic'
import { formatPct, isUnresolvedHarness } from './overviewCopy'

/** Bars for rows the SDK could not identify, so they read as absence rather than as another client. */
const UNRESOLVED_BAR_COLOR = 'var(--color-border-secondary)'

/** Above this share of new people failing their first call, the number is the headline problem. */
const FIRST_CALL_FAILED_DANGER_PCT = 5

function ShareBar({
    label,
    meta,
    value,
    max,
    color,
    muted,
    icon,
}: {
    label: string
    meta: JSX.Element
    value: number
    max: number
    color: string
    muted?: boolean
    icon?: JSX.Element
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className={cn('flex min-w-0 items-center gap-1.5 truncate', muted && 'text-muted')} title={label}>
                    {icon}
                    <span className="truncate">{label}</span>
                </span>
                <span className="whitespace-nowrap text-muted" translate="no">
                    {meta}
                </span>
            </div>
            <LemonProgress
                percent={max > 0 ? (value / max) * 100 : 0}
                strokeColor={color}
                bgColor="var(--color-bg-surface-tertiary)"
            />
        </div>
    )
}

function Stat({
    label,
    value,
    detail,
    danger,
}: {
    label: string
    value: string
    detail: string
    danger?: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-xs text-muted">{label}</span>
            <span
                className={cn('text-xl font-semibold leading-7', danger ? 'text-danger' : 'text-primary')}
                translate="no"
            >
                {value}
            </span>
            <span className="text-sm text-muted">{detail}</span>
        </div>
    )
}

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted">{title}</span>
            <div className="flex flex-col gap-1.5">{children}</div>
        </div>
    )
}

function ClientSection(): JSX.Element {
    const { clientRows } = useValues(mcpOverviewLogic)
    const max = Math.max(...clientRows.map((row) => row.total_calls), 0)

    if (clientRows.length === 0) {
        return (
            <Section title="By client">
                <span className="text-sm text-muted">No calls in this range.</span>
            </Section>
        )
    }
    return (
        <Section title="By client">
            {clientRows.map((row) => {
                const unresolved = isUnresolvedHarness(row.harness)
                return (
                    <ShareBar
                        key={row.harness}
                        label={row.harness}
                        icon={unresolved ? undefined : <HarnessLogo category={row.harness} className="h-3.5 w-3.5" />}
                        meta={
                            <>
                                {formatNumber(row.total_calls)}
                                {row.errors > 0 ? (
                                    <span className="text-danger"> · {formatPct(row.error_rate_pct)} err</span>
                                ) : null}
                            </>
                        }
                        value={row.total_calls}
                        max={max}
                        muted={unresolved}
                        color={unresolved ? UNRESOLVED_BAR_COLOR : 'var(--data-color-1)'}
                    />
                )
            })}
        </Section>
    )
}

function ModelSection(): JSX.Element | null {
    const { modelRowsRanked } = useValues(mcpOverviewLogic)
    const max = Math.max(...modelRowsRanked.map((row) => row.total_calls), 0)

    if (modelRowsRanked.length === 0) {
        return null
    }
    return (
        <Section title="By model">
            {modelRowsRanked.map((row) => {
                const unknown = row.model === 'Unknown'
                return (
                    <ShareBar
                        key={row.model}
                        label={row.model}
                        meta={
                            <>
                                {formatNumber(row.total_calls)}
                                {row.errors > 0 ? (
                                    <span className="text-danger"> · {formatPct(row.error_rate_pct)} err</span>
                                ) : null}
                            </>
                        }
                        value={row.total_calls}
                        max={max}
                        muted={unknown}
                        color={unknown ? UNRESOLVED_BAR_COLOR : 'var(--data-color-2)'}
                    />
                )
            })}
        </Section>
    )
}

/** Who reached the server in this window, and whether their first try worked. */
export function WhoCard(): JSX.Element {
    const { summary, summaryLoading } = useValues(mcpOverviewLogic)

    return (
        <Card size="sm" className="gap-0">
            <CardHeader className="border-b border-border pb-3">
                <CardTitle>Who is using it</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 pt-3">
                {summaryLoading && !summary ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-10 w-full" />
                        <LemonSkeleton className="h-10 w-full" />
                    </div>
                ) : (
                    <div className="grid grid-cols-2 gap-3">
                        <Stat
                            label="New people"
                            value={formatNumber(summary?.new_people ?? 0)}
                            detail={`of ${formatNumber(summary?.people ?? 0)} people`}
                        />
                        <Stat
                            label="First call failed"
                            value={formatPct(summary?.new_people_first_call_failed_pct ?? 0)}
                            detail="of new people"
                            danger={(summary?.new_people_first_call_failed_pct ?? 0) > FIRST_CALL_FAILED_DANGER_PCT}
                        />
                    </div>
                )}
                <ClientSection />
                <ModelSection />
            </CardContent>
        </Card>
    )
}
