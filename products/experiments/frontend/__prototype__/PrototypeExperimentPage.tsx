/** Scratch prototype of the experiment detail page. Not product code; not committed. */
import { useMemo, useState } from 'react'

import {
    IconCheckCircle,
    IconCircleDashed,
    IconCopy,
    IconEllipsis,
    IconFlag,
    IconFlask,
    IconPencil,
    IconPlay,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, LemonTabs, LemonTag } from '@posthog/lemon-ui'
import { type Series, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { cn } from 'lib/utils/css-classes'

import {
    EXPERIMENT,
    EXPOSURES,
    HEALTH_ISSUES,
    PRIMARY_METRICS,
    PROTOTYPE_STATUS,
    type PrototypeMetric,
    type PrototypeStatus,
    SECONDARY_METRICS,
    VARIANTS,
} from './prototypeData'

function axisLimit(metrics: PrototypeMetric[]): number {
    const widest = Math.max(
        ...metrics.flatMap((metric) =>
            metric.variants.flatMap((variant) => (variant.interval ? variant.interval.map(Math.abs) : [0]))
        )
    )
    return Math.ceil(widest * 20) / 20
}

function useVariantColors(): Record<string, string> {
    const theme = useChartTheme()
    return useMemo(
        () => Object.fromEntries(VARIANTS.map((key, index) => [key, theme.colors[index % theme.colors.length]])),
        [theme]
    )
}

function VariantDot({ color }: { color: string }): JSX.Element {
    return <span className="inline-block size-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
}

function formatDelta(delta: number): string {
    return `${delta > 0 ? '+' : ''}${(delta * 100).toFixed(1)}%`
}

function formatChance(chance: number): string {
    if (chance >= 0.995) {
        return '> 99%'
    }
    if (chance <= 0.005) {
        return '< 1%'
    }
    return `${Math.round(chance * 100)}%`
}

function StatusTag({ status }: { status: PrototypeStatus }): JSX.Element {
    const type = {
        draft: 'default',
        running: 'success',
        paused: 'warning',
        complete: 'completion',
    } as const
    return (
        <LemonTag type={type[status]}>
            <b className="uppercase">{status}</b>
        </LemonTag>
    )
}

function HealthChip(): JSX.Element {
    return (
        <LemonTag type="warning" icon={<IconWarning />}>
            {HEALTH_ISSUES.length} issues
        </LemonTag>
    )
}

function RefreshText(): JSX.Element {
    return (
        <span className="text-xs text-secondary whitespace-nowrap">
            Refreshed 9 minutes ago ·{' '}
            <button type="button" className="text-link hover:underline cursor-pointer">
                Refresh
            </button>
        </span>
    )
}

function HeaderActions({ status }: { status: PrototypeStatus }): JSX.Element {
    return (
        <div className="flex items-center gap-2 shrink-0">
            {status === PROTOTYPE_STATUS.draft && (
                <LemonButton type="primary" size="small">
                    Launch
                </LemonButton>
            )}
            {status === PROTOTYPE_STATUS.running && (
                <LemonButton type="primary" size="small" icon={<IconFlask />}>
                    End experiment
                </LemonButton>
            )}
            {status === PROTOTYPE_STATUS.paused && (
                <LemonButton type="primary" size="small" icon={<IconPlay />}>
                    Resume
                </LemonButton>
            )}
            <LemonButton type="secondary" size="small" icon={<IconEllipsis />} aria-label="More actions" />
        </div>
    )
}

function HeaderFacts({ status }: { status: PrototypeStatus }): JSX.Element {
    return (
        <div className="flex items-center gap-3 text-xs">
            {status === PROTOTYPE_STATUS.draft && <span className="text-secondary">~14 days estimated</span>}
            {status === PROTOTYPE_STATUS.running && (
                <>
                    <span className="flex items-center gap-1.5">
                        <span className="w-16 h-1.5 rounded-full bg-fill-tertiary overflow-hidden">
                            <span className="block h-full bg-success" style={{ width: '64%' }} />
                        </span>
                        <span>Day 9 of ~14</span>
                    </span>
                    <RefreshText />
                </>
            )}
            {status === PROTOTYPE_STATUS.paused && (
                <span className="text-secondary">Paused on Nov 12 · day 9 of ~14</span>
            )}
            {status === PROTOTYPE_STATUS.complete && (
                <span className="text-secondary">
                    {EXPERIMENT.startDate} → {EXPERIMENT.endDate} · 14 days
                </span>
            )}
        </div>
    )
}

function CompactVerdict({ status }: { status: PrototypeStatus }): JSX.Element | null {
    if (status === PROTOTYPE_STATUS.draft) {
        return <span className="text-xs text-secondary truncate">2 of 4 launch steps done</span>
    }
    if (status === PROTOTYPE_STATUS.complete) {
        return (
            <span className="text-xs truncate">
                <LemonTag type="success">Won</LemonTag> Shipped <b>one-page</b>
            </span>
        )
    }
    return (
        <span className="text-xs truncate">
            <b>one-page</b> leads on Checkout completed <span className="text-success font-semibold">+8.4%</span>{' '}
            <span className="text-secondary">· 99% chance to win</span>
        </span>
    )
}

function StickyHeader({ status, compact }: { status: PrototypeStatus; compact: boolean }): JSX.Element {
    return (
        <div
            className={cn(
                'sticky top-0 z-20 bg-primary border-b transition-[padding] motion-reduce:transition-none',
                compact ? 'py-2' : 'pt-4 pb-3'
            )}
        >
            <div className="flex items-center gap-3 min-w-0">
                <IconFlask className={cn('text-secondary shrink-0', compact ? 'text-base' : 'text-xl')} />
                <h1 className={cn('m-0 font-semibold truncate', compact ? 'text-sm' : 'text-xl')}>{EXPERIMENT.name}</h1>
                {!compact && <IconPencil className="text-secondary shrink-0" />}
                <StatusTag status={status} />
                {(status === PROTOTYPE_STATUS.running || status === PROTOTYPE_STATUS.paused) && <HealthChip />}
                {compact && (
                    <div className="min-w-0 flex-1 flex items-center gap-3 border-l pl-3">
                        <CompactVerdict status={status} />
                    </div>
                )}
                <div className={cn('flex items-center gap-4', !compact && 'ml-auto')}>
                    <HeaderFacts status={status} />
                    <HeaderActions status={status} />
                </div>
            </div>
        </div>
    )
}

function VerdictStrip({ status }: { status: PrototypeStatus }): JSX.Element {
    if (status === PROTOTYPE_STATUS.draft) {
        return <LaunchChecklist />
    }
    if (status === PROTOTYPE_STATUS.complete) {
        return (
            <div className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                            <LemonTag type="success" size="medium">
                                <b>WON</b>
                            </LemonTag>
                            <span className="text-lg font-semibold">
                                Shipped <span className="font-mono">one-page</span> to 100% of users
                            </span>
                        </div>
                        <p className="m-0 mt-2 text-sm">
                            One-page checkout lifted completed checkouts by 8.4% with no drop in revenue per user. We
                            rolled it out to everyone on Nov 16.
                        </p>
                    </div>
                    <LemonButton size="small" type="secondary" icon={<IconPencil />}>
                        Edit conclusion
                    </LemonButton>
                </div>
                <div className="flex items-center gap-2 text-sm border-t pt-3">
                    <IconWarning className="text-warning text-base shrink-0" />
                    <span className="flex-1">
                        The flag <span className="font-mono">{EXPERIMENT.flagKey}</span> still serves 3 variants. Roll
                        out one-page to everyone or turn off the flag.
                    </span>
                    <LemonButton size="small" type="secondary" icon={<IconFlag />}>
                        Open feature flag
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="border rounded bg-surface-primary p-4 flex items-center gap-6">
            <div className="flex-1 min-w-0">
                <div className="text-xs text-secondary uppercase font-semibold tracking-wide">
                    Checkout completed · primary metric 1 of 3
                </div>
                <div className="mt-1 text-lg font-semibold">
                    <span className="font-mono">one-page</span> leads with <span className="text-success">+8.4%</span>{' '}
                    completed checkouts
                </div>
                <div className="mt-1 text-sm text-secondary">
                    99% chance to win · 95% credible interval +3.1% to +13.9% · 1 of 3 primary metrics significant
                </div>
            </div>
            {status === PROTOTYPE_STATUS.paused ? (
                <div className="flex items-center gap-2 text-sm max-w-80">
                    <IconWarning className="text-warning text-base shrink-0" />
                    <span>Paused. The flag is off and no new data is collected.</span>
                </div>
            ) : (
                <div className="flex items-center gap-2 text-sm text-secondary max-w-80">
                    <span>About 5 days left to reach the target of 18,000 exposures.</span>
                </div>
            )}
        </div>
    )
}

function LaunchChecklist(): JSX.Element {
    const steps = [
        {
            done: false,
            label: 'Add the feature flag to your code',
            detail: `Use the flag key ${EXPERIMENT.flagKey}.`,
            action: 'View code',
        },
        { done: true, label: 'Add a primary metric', detail: '3 primary and 2 secondary metrics added.', action: null },
        { done: true, label: 'Review exposure criteria', detail: EXPOSURES.criteria, action: 'Edit' },
        {
            done: false,
            label: 'Set a running time target',
            detail: 'We estimate about 14 days at current traffic.',
            action: 'Set target',
        },
    ]
    return (
        <div className="border rounded bg-surface-primary p-4">
            <div className="flex items-center justify-between">
                <div className="font-semibold">Before you launch</div>
                <div className="text-xs text-secondary">2 of 4 done</div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2">
                {steps.map((step) => (
                    <div key={step.label} className="flex items-start gap-2 py-1">
                        {step.done ? (
                            <IconCheckCircle className="text-success text-lg shrink-0 mt-0.5" />
                        ) : (
                            <IconCircleDashed className="text-secondary text-lg shrink-0 mt-0.5" />
                        )}
                        <div className="flex-1 min-w-0">
                            <div className={cn('text-sm', step.done ? 'text-secondary' : 'font-semibold')}>
                                {step.label}
                            </div>
                            <div className="text-xs text-secondary">{step.detail}</div>
                        </div>
                        {step.action && (
                            <LemonButton size="xsmall" type="secondary">
                                {step.action}
                            </LemonButton>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}

function IntervalBar({ interval, limit }: { interval: [number, number]; limit: number }): JSX.Element {
    const left = ((interval[0] + limit) / (2 * limit)) * 100
    const right = ((interval[1] + limit) / (2 * limit)) * 100
    const tone = interval[0] > 0 ? 'bg-success' : interval[1] < 0 ? 'bg-danger' : ''
    return (
        <span
            className={cn('absolute top-1/2 -translate-y-1/2 h-2 rounded-full', tone)}
            style={{
                left: `calc(${left}% )`,
                width: `${right - left}%`,
                ...(tone ? {} : { backgroundColor: 'var(--color-text-tertiary)', opacity: 0.45 }),
            }}
        />
    )
}

function AxisCell({ children }: { children?: React.ReactNode }): JSX.Element {
    return (
        <td className="w-[30%] px-3">
            <div className="relative h-9">
                <span className="absolute top-0 bottom-0 left-1/2 border-l border-dashed border-primary" />
                {children}
            </div>
        </td>
    )
}

function MetricsTable({
    title,
    metrics,
    status,
}: {
    title: string
    metrics: PrototypeMetric[]
    status: PrototypeStatus
}): JSX.Element {
    const colors = useVariantColors()
    const isDraft = status === PROTOTYPE_STATUS.draft
    const limit = axisLimit(metrics)
    const tick = `${Math.round(limit * 100)}%`
    return (
        <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <h2 className="m-0 text-base font-semibold">{title}</h2>
                <LemonButton size="small" type="tertiary">
                    Add metric
                </LemonButton>
            </div>
            <div className="border rounded bg-surface-primary">
                <table className="w-full text-sm border-collapse">
                    <thead className="sticky top-12 z-10 bg-surface-secondary">
                        <tr className="text-xs text-secondary uppercase text-left">
                            <th className="px-3 py-2 font-semibold w-[20%]">Metric</th>
                            <th className="px-3 py-2 font-semibold">Variant</th>
                            <th className="px-3 py-2 font-semibold text-right">Value</th>
                            <th className="px-3 py-2 font-semibold text-right">Delta</th>
                            <th className="px-3 py-2 font-semibold text-right whitespace-nowrap">Chance to win</th>
                            <th className="px-3 py-2 font-semibold">
                                {!isDraft && (
                                    <div className="flex justify-between font-normal normal-case">
                                        <span>-{tick}</span>
                                        <span>0%</span>
                                        <span>+{tick}</span>
                                    </div>
                                )}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {metrics.map((metric, metricIndex) =>
                            metric.variants.map((variant, variantIndex) => {
                                const significant =
                                    variant.interval !== null && (variant.interval[0] > 0 || variant.interval[1] < 0)
                                return (
                                    <tr
                                        key={`${metric.name}-${variant.key}`}
                                        className={cn(variantIndex === 0 && metricIndex > 0 && 'border-t', 'h-9')}
                                    >
                                        {variantIndex === 0 && (
                                            <td
                                                rowSpan={metric.variants.length}
                                                className="px-3 py-2 align-top border-r"
                                            >
                                                <div className="font-semibold">
                                                    {metricIndex + 1}. {metric.name}
                                                </div>
                                                <LemonTag size="small" className="mt-1">
                                                    {metric.kind}
                                                </LemonTag>
                                            </td>
                                        )}
                                        <td className="px-3 whitespace-nowrap">
                                            <span className="flex items-center gap-2">
                                                <VariantDot color={colors[variant.key]} />
                                                <span className="font-mono text-xs">{variant.key}</span>
                                            </span>
                                        </td>
                                        {isDraft ? (
                                            variantIndex === 0 ? (
                                                <td
                                                    colSpan={4}
                                                    rowSpan={metric.variants.length}
                                                    className="px-3 text-secondary text-xs text-center"
                                                >
                                                    Results show after launch
                                                </td>
                                            ) : null
                                        ) : (
                                            <>
                                                <td className="px-3 py-1 text-right tabular-nums whitespace-nowrap">
                                                    {variant.value}
                                                    <div className="text-xs text-secondary">{variant.detail}</div>
                                                </td>
                                                <td
                                                    className={cn(
                                                        'px-3 text-right tabular-nums font-semibold',
                                                        significant &&
                                                            variant.delta !== null &&
                                                            variant.delta > 0 &&
                                                            'text-success',
                                                        significant &&
                                                            variant.delta !== null &&
                                                            variant.delta < 0 &&
                                                            'text-danger',
                                                        !significant && 'text-secondary font-normal'
                                                    )}
                                                >
                                                    {variant.delta === null ? 'Baseline' : formatDelta(variant.delta)}
                                                </td>
                                                <td className="px-3 text-right tabular-nums">
                                                    {variant.chanceToWin === null
                                                        ? ''
                                                        : formatChance(variant.chanceToWin)}
                                                </td>
                                                <AxisCell>
                                                    {variant.interval && (
                                                        <IntervalBar interval={variant.interval} limit={limit} />
                                                    )}
                                                </AxisCell>
                                            </>
                                        )}
                                    </tr>
                                )
                            })
                        )}
                    </tbody>
                </table>
            </div>
        </section>
    )
}

function RailCard({
    title,
    action,
    children,
}: {
    title: string
    action?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="border rounded bg-surface-primary">
            <div className="flex items-center justify-between px-3 py-2 border-b">
                <span className="text-xs uppercase font-semibold text-secondary tracking-wide">{title}</span>
                {action}
            </div>
            <div className="p-3">{children}</div>
        </div>
    )
}

function ExposuresChart(): JSX.Element {
    const theme = useChartTheme()
    const series: Series[] = useMemo(() => VARIANTS.map((key) => ({ key, label: key, data: EXPOSURES.daily[key] })), [])
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({ xAxis: { interval: 'day', timezone: 'UTC' }, tooltip: { placement: 'cursor' } }),
        []
    )
    return (
        <div className="relative h-[140px] flex flex-col">
            <TimeSeriesLineChart series={series} labels={EXPOSURES.days} theme={theme} config={config} />
        </div>
    )
}

function ExposuresCard({ status }: { status: PrototypeStatus }): JSX.Element {
    const colors = useVariantColors()
    const editButton = (
        <LemonButton size="xsmall" type="tertiary" icon={<IconPencil />} aria-label="Edit exposure criteria" />
    )
    if (status === PROTOTYPE_STATUS.draft) {
        return (
            <RailCard title="Exposures" action={editButton}>
                <div className="text-sm">{EXPOSURES.criteria}</div>
                <div className="text-xs text-secondary mt-1">Counts show after launch. Target split 33% each.</div>
            </RailCard>
        )
    }
    return (
        <RailCard title="Exposures" action={editButton}>
            <div className="flex items-baseline justify-between">
                <span className="text-2xl font-semibold tabular-nums">{EXPOSURES.total}</span>
                <span className="text-xs text-secondary">{EXPOSURES.criteria}</span>
            </div>
            <div className="mt-2 flex flex-col gap-1">
                {EXPOSURES.split.map((row) => (
                    <div key={row.key} className="flex items-center gap-2 text-xs">
                        <VariantDot color={colors[row.key]} />
                        <span className="font-mono flex-1">{row.key}</span>
                        <span className="tabular-nums">{row.count}</span>
                        <span className="tabular-nums text-secondary w-12 text-right">{row.share}</span>
                    </div>
                ))}
            </div>
            <div className="mt-2 flex items-center gap-1.5 text-xs text-secondary">
                <IconCheckCircle className="text-success" />
                Split matches the target (p = 0.94)
            </div>
            <div className="mt-3 text-xs text-secondary">Exposures per day</div>
            <div className="mt-1">
                <ExposuresChart />
            </div>
        </RailCard>
    )
}

function HealthCard(): JSX.Element {
    return (
        <RailCard
            title="Health"
            action={
                <LemonButton size="xsmall" type="tertiary">
                    View all
                </LemonButton>
            }
        >
            <div className="flex flex-col gap-2">
                {HEALTH_ISSUES.map((issue) => (
                    <div key={issue.title} className="flex items-start gap-2">
                        <IconWarning className="text-warning text-base shrink-0 mt-0.5" />
                        <div>
                            <div className="text-sm font-semibold">{issue.title}</div>
                            <div className="text-xs text-secondary">{issue.detail}</div>
                        </div>
                    </div>
                ))}
            </div>
        </RailCard>
    )
}

function HypothesisCard(): JSX.Element {
    return (
        <RailCard
            title="Hypothesis"
            action={<LemonButton size="xsmall" type="tertiary" icon={<IconPencil />} aria-label="Edit hypothesis" />}
        >
            <p className="m-0 text-sm">{EXPERIMENT.hypothesis}</p>
        </RailCard>
    )
}

function AboutCard({ status }: { status: PrototypeStatus }): JSX.Element {
    const rows: [string, React.ReactNode][] = [
        [
            'Feature flag',
            <span key="flag" className="flex items-center gap-1 min-w-0">
                <IconFlag className="text-secondary shrink-0" />
                <span className="font-mono truncate">{EXPERIMENT.flagKey}</span>
                <IconCopy className="text-secondary shrink-0" />
            </span>,
        ],
        ['Statistics', `${EXPERIMENT.statsMethod} · ${EXPERIMENT.confidence}`],
        [
            'Dates',
            status === PROTOTYPE_STATUS.draft
                ? 'Not started'
                : status === PROTOTYPE_STATUS.complete
                  ? `${EXPERIMENT.startDate} → ${EXPERIMENT.endDate}`
                  : `${EXPERIMENT.startDate} → now`,
        ],
        ['Variants', '3 · equal split'],
        [
            'Created by',
            <span key="owner" className="flex items-center gap-1.5">
                <span className="size-5 rounded-full bg-fill-tertiary flex items-center justify-center text-xs font-semibold">
                    {EXPERIMENT.ownerInitial}
                </span>
                {EXPERIMENT.owner}
            </span>,
        ],
    ]
    return (
        <RailCard title="About">
            <dl className="m-0 grid grid-cols-[96px_1fr] gap-y-2 text-sm">
                {rows.map(([label, value]) => (
                    <div key={label} className="contents">
                        <dt className="text-secondary text-xs self-center">{label}</dt>
                        <dd className="m-0 min-w-0 truncate">{value}</dd>
                    </div>
                ))}
            </dl>
        </RailCard>
    )
}

function ResultsTab({ status }: { status: PrototypeStatus }): JSX.Element {
    const showHealth = status === PROTOTYPE_STATUS.running || status === PROTOTYPE_STATUS.paused
    return (
        <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-4 items-start">
            <div className="flex flex-col gap-6 min-w-0">
                <MetricsTable title="Primary metrics" metrics={PRIMARY_METRICS} status={status} />
                <MetricsTable title="Secondary metrics" metrics={SECONDARY_METRICS} status={status} />
            </div>
            <aside className="sticky top-14 flex flex-col gap-3">
                <ExposuresCard status={status} />
                {showHealth && <HealthCard />}
                <HypothesisCard />
                <AboutCard status={status} />
            </aside>
        </div>
    )
}

function PrototypeTabs({ status }: { status: PrototypeStatus }): JSX.Element {
    const labels = [
        ['results', 'Results'],
        ['health', 'Health'],
        ['recordings', 'Recordings'],
        ['feedback', 'User feedback'],
        ['settings', 'Settings'],
        ['variants', 'Variants'],
        ['code', 'Code'],
        ['history', 'History'],
    ] as const
    return (
        <LemonTabs
            activeKey="results"
            onChange={() => {}}
            tabs={labels.map(([key, label]) => ({
                key,
                label,
                content: key === 'results' ? <ResultsTab status={status} /> : null,
            }))}
        />
    )
}

/** Fake app navigation so the content area has the same width as the real app at 1440px. */
function FakeAppNav(): JSX.Element {
    return (
        <div className="w-[220px] shrink-0 bg-surface-secondary border-r h-full p-3 flex flex-col gap-2">
            {['Home', 'Activity', 'Product analytics', 'Experiments', 'Feature flags'].map((item) => (
                <div key={item} className="h-6 rounded bg-fill-tertiary opacity-50" title={item} />
            ))}
        </div>
    )
}

export function PrototypeExperimentPage({ status }: { status: PrototypeStatus }): JSX.Element {
    const [compact, setCompact] = useState(false)
    return (
        <div className="flex h-screen bg-primary">
            <FakeAppNav />
            <div
                className="flex-1 min-w-0 overflow-y-auto px-6"
                data-attr="prototype-scroll"
                onScroll={(event) => setCompact(event.currentTarget.scrollTop > 80)}
            >
                <StickyHeader status={status} compact={compact} />
                <div className="pt-4 pb-10 flex flex-col gap-4">
                    <VerdictStrip status={status} />
                    <PrototypeTabs status={status} />
                </div>
            </div>
        </div>
    )
}
