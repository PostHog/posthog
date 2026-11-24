/** Scratch prototype v6: v5 with full-width metric rows, icon metric actions and a phone frame. Not committed. */
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    IconCheckCircle,
    IconCircleDashed,
    IconCopy,
    IconEllipsis,
    IconFlag,
    IconDrag,
    IconFilter,
    IconFlask,
    IconGraph,
    IconPencil,
    IconRewindPlay,
    IconWarning,
} from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardAction,
    CardContent,
    CardHeader,
    CardTitle,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Progress,
    Separator,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
    cn,
} from '@posthog/quill'
import { Sparkline, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import { QuillSceneHeader } from '~/layout/scenes/components/QuillSceneHeader'

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
import { metricTrends } from './prototypeTimeseries'
import { PrototypeTrendChart } from './PrototypeTrendChart'

export const SHELL_STATE = { sidebarOpen: 'sidebar-open', sidebarClosed: 'sidebar-closed', phone: 'phone' } as const
export type ShellState = (typeof SHELL_STATE)[keyof typeof SHELL_STATE]

export const RUN_PROGRESS = { inProgress: 'in-progress', targetReached: 'target-reached' } as const
export type RunProgress = (typeof RUN_PROGRESS)[keyof typeof RUN_PROGRESS]

/** Scroll distance after which the summary has left the view and the status line carries its short form. */
const COMPACT_AFTER_PX = 200

const ROW_HEIGHT = 48

function useVariantColors(): Record<string, string> {
    const theme = useChartTheme()
    return useMemo(
        () => Object.fromEntries(VARIANTS.map((key, index) => [key, theme.colors[index % theme.colors.length]])),
        [theme]
    )
}

function axisLimit(metrics: PrototypeMetric[]): number {
    const widest = Math.max(
        ...metrics.flatMap((metric) =>
            metric.variants.flatMap((variant) => (variant.interval ? variant.interval.map(Math.abs) : [0]))
        )
    )
    return Math.ceil(widest * 20) / 20
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

function VariantDot({ color }: { color: string }): JSX.Element {
    return <span className="inline-block size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
}

function StatusBadge({ status }: { status: PrototypeStatus }): JSX.Element {
    const variant = { draft: 'default', running: 'success', paused: 'warning', complete: 'completed' } as const
    const label = { draft: 'Draft', running: 'Running', paused: 'Paused', complete: 'Complete' }
    return <Badge variant={variant[status]}>{label[status]}</Badge>
}

/** Placeholder for the rail and the Products sidebar, so the scene gets its real width. */
function FakeShell({ shell }: { shell: ShellState }): JSX.Element | null {
    if (shell === SHELL_STATE.phone) {
        return null
    }
    return (
        <>
            <div className="flex w-15 shrink-0 flex-col items-center gap-3 border-r border-border bg-chrome py-3">
                {Array.from({ length: 5 }, (_, index) => (
                    <div key={index} className="size-8 rounded-md bg-fill-hover" />
                ))}
            </div>
            {shell === SHELL_STATE.sidebarOpen && (
                <div className="flex w-72 shrink-0 flex-col gap-2 border-r border-border bg-chrome p-3">
                    <div className="h-10.5 -mx-3 -mt-3 mb-1 border-b border-border" />
                    {Array.from({ length: 12 }, (_, index) => (
                        <div key={index} className="h-5 rounded-sm bg-fill-hover" />
                    ))}
                </div>
            )}
        </>
    )
}

/** Placeholder for the phone header the real shell shows instead of the rail. */
function FakePhoneHeader(): JSX.Element {
    return (
        <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-chrome px-3">
            <div className="size-7 rounded-md bg-fill-hover" />
            <div className="h-4 w-28 rounded-sm bg-fill-hover" />
            <div className="ml-auto size-7 rounded-md bg-fill-hover" />
        </div>
    )
}

function SceneActions({ status }: { status: PrototypeStatus }): JSX.Element {
    return (
        <>
            {status === PROTOTYPE_STATUS.draft && <Button variant="primary">Launch</Button>}
            {status === PROTOTYPE_STATUS.running && (
                <Button variant="primary">
                    <IconFlask />
                    End experiment
                </Button>
            )}
            <Button size="icon" aria-label="More actions" tooltip="More actions">
                <IconEllipsis />
            </Button>
        </>
    )
}

function SceneTitle(): JSX.Element {
    return (
        <>
            <Text size="xs" variant="muted" render={<span />}>
                Experiments
            </Text>
            <Text size="xs" variant="muted" render={<span />}>
                /
            </Text>
            <Text size="xs" weight="medium" render={<span className="truncate" />}>
                {EXPERIMENT.name}
            </Text>
            <Separator orientation="vertical" className="mx-2 h-4" />
            {['File', 'Edit', 'Help'].map((menu) => (
                <Button key={menu} size="sm">
                    {menu}
                </Button>
            ))}
        </>
    )
}

/** The status line wraps on a narrow scene, so the sticky table header and right column read its height. */
function useHeight(): [React.RefObject<HTMLDivElement>, number] {
    const ref = useRef<HTMLDivElement>(null)
    const [height, setHeight] = useState(0)
    useEffect(() => {
        if (!ref.current) {
            return
        }
        const observer = new ResizeObserver(([entry]) => setHeight(entry.target.getBoundingClientRect().height))
        observer.observe(ref.current)
        return () => observer.disconnect()
    }, [])
    return [ref, height]
}

function MetaLine({
    status,
    progress,
    compact,
    lineRef,
}: {
    status: PrototypeStatus
    progress: RunProgress
    compact: boolean
    lineRef: React.RefObject<HTMLDivElement>
}): JSX.Element {
    const isRunning = status === PROTOTYPE_STATUS.running
    const targetReached = progress === RUN_PROGRESS.targetReached
    return (
        <div
            ref={lineRef}
            data-attr="prototype-status-line"
            className={cn(
                'sticky top-0 z-20 -mx-4 flex flex-wrap items-center gap-x-3 gap-y-1 bg-background px-4 py-2',
                compact && 'border-b border-border shadow-sm'
            )}
        >
            <StatusBadge status={status} />
            {isRunning && (
                <Badge variant="warning">
                    <IconWarning />
                    {HEALTH_ISSUES.length} issues
                </Badge>
            )}
            {isRunning && (
                <div className="flex items-center gap-2">
                    <Progress value={targetReached ? 100 : 64} variant="success" className="w-16" />
                    <Text size="xs" render={<span />}>
                        {targetReached ? 'Target reached · day 14' : 'Day 9 of ~14'}
                    </Text>
                </div>
            )}
            {isRunning && (
                <Text size="xs" variant="muted" render={<span />}>
                    {EXPERIMENT.startDate} → now
                </Text>
            )}
            {status === PROTOTYPE_STATUS.draft && (
                <Text size="xs" variant="muted" render={<span />}>
                    ~14 days estimated
                </Text>
            )}
            {status === PROTOTYPE_STATUS.complete && (
                <Text size="xs" variant="muted" render={<span />}>
                    {EXPERIMENT.startDate} → {EXPERIMENT.endDate} · 14 days
                </Text>
            )}
            {compact && isRunning && (
                <>
                    <Separator orientation="vertical" className="h-4" />
                    <Text size="xs" render={<span className="min-w-0 truncate" />}>
                        <span className="font-mono">one-page</span> {targetReached ? 'won' : 'leads'} on Checkout
                        completed <span className="text-success-foreground">+8.4%</span>
                    </Text>
                </>
            )}
            <div className="ml-auto flex items-center gap-3">
                {isRunning && (
                    <Text size="xs" variant="muted" render={<span className="whitespace-nowrap" />}>
                        Refreshed 9 minutes ago ·{' '}
                        <Button variant="link" size="inline">
                            Refresh
                        </Button>
                    </Text>
                )}
                {compact && isRunning && (
                    <Button variant={targetReached ? 'primary' : 'outline'} size="sm">
                        Release one-page
                    </Button>
                )}
            </div>
        </div>
    )
}

const REASONS = [
    {
        tone: 'good',
        title: 'Checkout completed, the first primary metric, went up 8.4%',
        detail: '99% chance to win. The 95% credible interval, +3.1% to +13.9%, is above zero.',
    },
    {
        tone: 'good',
        title: 'No other primary metric got worse',
        detail: 'Revenue per user +4.3% (93% chance to win). Items per order -1.3%, not significant.',
    },
    {
        tone: 'good',
        title: 'Secondary metrics show no harm',
        detail: 'Support tickets and payment errors have no significant change.',
    },
    {
        tone: 'warning',
        title: '2 health issues to review',
        detail: 'Exposures dropped on Nov 8, and 2% of users saw more than one variant. Neither changes the result.',
    },
] as const

function SummaryReport({ progress }: { progress: RunProgress }): JSX.Element {
    const targetReached = progress === RUN_PROGRESS.targetReached
    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>
                    <span className="flex items-center gap-2">
                        <Heading size="sm" render={<h2 className="m-0" />}>
                            Summary
                        </Heading>
                        {targetReached ? (
                            <Badge variant="success">Target reached</Badge>
                        ) : (
                            <Badge>Results can still change</Badge>
                        )}
                    </span>
                </CardTitle>
                <CardAction>
                    <span className="flex items-center gap-1">
                        <Button variant="outline" className="hidden @lg/main-content:inline-flex">
                            Review results
                        </Button>
                        <Button variant={targetReached ? 'primary' : 'outline'}>Release one-page</Button>
                    </span>
                </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <Heading size="base" render={<p className="m-0" />}>
                        <span className="font-mono">one-page</span> {targetReached ? 'won' : 'leads'} on Checkout
                        completed with <span className="text-success-foreground">+8.4%</span> completed checkouts
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {targetReached
                            ? 'The experiment reached its target of 18,000 exposures. We recommend releasing one-page.'
                            : 'The experiment has 12,480 of its 18,000 target exposures, about 5 days left. Releasing now ends the experiment early.'}
                    </Text>
                </div>
                <div className="grid grid-cols-1 gap-x-6 gap-y-2 @4xl/main-content:grid-cols-2">
                    {REASONS.map((reason) => (
                        <div key={reason.title} className="flex items-start gap-2">
                            {reason.tone === 'good' ? (
                                <IconCheckCircle className="mt-0.5 shrink-0 text-success-foreground" />
                            ) : (
                                <IconWarning className="mt-0.5 shrink-0 text-warning-foreground" />
                            )}
                            <div className="flex flex-col">
                                <Text size="xs" weight="medium" render={<span />}>
                                    {reason.title}
                                </Text>
                                <Text size="xs" variant="muted" render={<span />}>
                                    {reason.detail}
                                </Text>
                            </div>
                        </div>
                    ))}
                </div>
                <Separator />
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    compact-cart did not win: Items per order went down 5.2%. Releasing one-page ends the experiment and
                    serves one-page to 100% of users through the flag {EXPERIMENT.flagKey}.
                </Text>
            </CardContent>
        </Card>
    )
}

function Verdict({ status, progress }: { status: PrototypeStatus; progress: RunProgress }): JSX.Element {
    if (status === PROTOTYPE_STATUS.draft) {
        return <LaunchChecklist />
    }
    if (status === PROTOTYPE_STATUS.complete) {
        return (
            <Card size="sm">
                <CardContent className="flex flex-col gap-2">
                    <div className="flex items-start gap-2">
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <div className="flex items-center gap-2">
                                <Badge variant="success">Won</Badge>
                                <Heading size="base" render={<h2 className="m-0" />}>
                                    Shipped one-page to 100% of users
                                </Heading>
                            </div>
                            <Text size="xs" render={<p className="m-0" />}>
                                One-page checkout lifted completed checkouts by 8.4% with no drop in revenue per user.
                                We rolled it out to everyone on Nov 16.
                            </Text>
                        </div>
                        <Button variant="outline">
                            <IconPencil />
                            Edit conclusion
                        </Button>
                    </div>
                    <Separator />
                    <div className="flex items-center gap-2">
                        <IconWarning className="shrink-0 text-warning-foreground" />
                        <Text size="xs" render={<p className="m-0 flex-1" />}>
                            The flag {EXPERIMENT.flagKey} still serves 3 variants. Roll out one-page to everyone or turn
                            off the flag.
                        </Text>
                        <Button variant="outline">
                            <IconFlag />
                            Open feature flag
                        </Button>
                    </div>
                </CardContent>
            </Card>
        )
    }
    return <SummaryReport progress={progress} />
}

function LaunchChecklist(): JSX.Element {
    const steps = [
        {
            done: false,
            title: 'Add the feature flag to your code',
            detail: `Use the flag key ${EXPERIMENT.flagKey}.`,
            action: 'View code',
        },
        { done: true, title: 'Add a primary metric', detail: '3 primary and 2 secondary metrics added.', action: null },
        { done: true, title: 'Review exposure criteria', detail: EXPOSURES.criteria, action: 'Edit' },
        {
            done: false,
            title: 'Set a running time target',
            detail: 'We estimate about 14 days at current traffic.',
            action: 'Set target',
        },
    ]
    return (
        <Card size="sm">
            <CardContent className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                    <Heading size="sm" render={<h2 className="m-0" />}>
                        Before you launch
                    </Heading>
                    <Text size="xs" variant="muted" render={<span />}>
                        2 of 4 done
                    </Text>
                </div>
                <ItemGroup className="grid grid-cols-1 gap-2 @3xl/main-content:grid-cols-2">
                    {steps.map((step) => (
                        <Item key={step.title} size="sm" variant="outline">
                            <ItemMedia>
                                {step.done ? (
                                    <IconCheckCircle className="text-success-foreground" />
                                ) : (
                                    <IconCircleDashed className="text-muted-foreground" />
                                )}
                            </ItemMedia>
                            <ItemContent>
                                <ItemTitle className={cn(step.done && 'text-muted-foreground')}>{step.title}</ItemTitle>
                                <ItemDescription>{step.detail}</ItemDescription>
                            </ItemContent>
                            {step.action && (
                                <ItemActions>
                                    <Button variant="outline" size="sm">
                                        {step.action}
                                    </Button>
                                </ItemActions>
                            )}
                        </Item>
                    ))}
                </ItemGroup>
            </CardContent>
        </Card>
    )
}

/** Wide scene: one column of cards beside the tables. Narrow scene: the same cards in a row above them. */
const PANEL_GRID =
    'grid grid-cols-1 gap-3 @lg/main-content:grid-cols-2 @5xl/main-content:grid-cols-4 @7xl/main-content:grid-cols-1'
const WIDE_ONLY = 'hidden @7xl/main-content:block'
const NARROW_ONLY = '@7xl/main-content:hidden'

function PanelCard({
    title,
    action,
    children,
}: {
    title: string
    action?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>
                    <Text size="xxs" variant="muted" weight="medium" render={<span className="uppercase" />}>
                        {title}
                    </Text>
                </CardTitle>
                {action && <CardAction>{action}</CardAction>}
            </CardHeader>
            <CardContent className="flex flex-col gap-2">{children}</CardContent>
        </Card>
    )
}

function ExposuresChart(): JSX.Element {
    const theme = useChartTheme()
    const colors = useVariantColors()
    const series = useMemo(
        () => VARIANTS.map((key) => ({ key, label: key, data: EXPOSURES.daily[key], color: colors[key] })),
        [colors]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({ xAxis: { interval: 'day', timezone: 'UTC' }, tooltip: { placement: 'cursor' } }),
        []
    )
    return (
        <div className="relative flex h-36 flex-col">
            <TimeSeriesLineChart series={series} labels={EXPOSURES.days} theme={theme} config={config} />
        </div>
    )
}

function ExposuresPanel({ status }: { status: PrototypeStatus }): JSX.Element {
    const colors = useVariantColors()
    const exposuresTotal = useMemo(
        () => EXPOSURES.days.map((_, index) => VARIANTS.reduce((sum, key) => sum + EXPOSURES.daily[key][index], 0)),
        []
    )
    const edit = (
        <Button size="icon-xs" aria-label="Edit exposure criteria" tooltip="Edit exposure criteria">
            <IconPencil />
        </Button>
    )
    if (status === PROTOTYPE_STATUS.draft) {
        return (
            <PanelCard title="Exposures" action={edit}>
                <Text size="xs" render={<p className="m-0" />}>
                    {EXPOSURES.criteria}
                </Text>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Counts show after launch. Target split 33% each.
                </Text>
            </PanelCard>
        )
    }
    return (
        <PanelCard title="Exposures" action={edit}>
            <div className="flex items-center gap-3">
                <Heading size="lg" render={<span />}>
                    {EXPOSURES.total}
                </Heading>
                <div className={cn('w-20', NARROW_ONLY)}>
                    <Sparkline data={exposuresTotal} height={24} />
                </div>
            </div>
            <div className="flex flex-col gap-0.5">
                {EXPOSURES.split.map((row) => (
                    <div key={row.key} className="flex items-center gap-2">
                        <VariantDot color={colors[row.key]} />
                        <Text size="xs" render={<span className="flex-1 font-mono" />}>
                            {row.key}
                        </Text>
                        <Text size="xs" render={<span className="tabular-nums" />}>
                            {row.count}
                        </Text>
                        <Text size="xs" variant="muted" render={<span className="w-12 text-right tabular-nums" />}>
                            {row.share}
                        </Text>
                    </div>
                ))}
            </div>
            <Text size="xs" variant="muted" render={<p className="m-0 flex items-center gap-1" />}>
                <IconCheckCircle className="text-success-foreground" />
                Split matches the target
            </Text>
            <div className={WIDE_ONLY}>
                <Text size="xs" variant="muted" render={<p className="m-0 mb-1" />}>
                    Exposures per day
                </Text>
                <ExposuresChart />
            </div>
        </PanelCard>
    )
}

function HealthPanel({ status }: { status: PrototypeStatus }): JSX.Element {
    return (
        <PanelCard
            title="Health"
            action={
                status === PROTOTYPE_STATUS.running ? (
                    <Button variant="link" size="inline">
                        View all
                    </Button>
                ) : undefined
            }
        >
            {status === PROTOTYPE_STATUS.running ? (
                HEALTH_ISSUES.map((issue) => (
                    <div key={issue.title} className="flex items-start gap-2">
                        <IconWarning className="mt-0.5 shrink-0 text-warning-foreground" />
                        <div className="flex flex-col">
                            <Text size="xs" weight="medium" render={<span />}>
                                {issue.title}
                            </Text>
                            <Text size="xs" variant="muted" render={<span className="line-clamp-2" />}>
                                {issue.detail}
                            </Text>
                        </div>
                    </div>
                ))
            ) : (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {status === PROTOTYPE_STATUS.draft ? 'Checks run after launch.' : 'No issues found.'}
                </Text>
            )}
        </PanelCard>
    )
}

function HypothesisPanel(): JSX.Element {
    return (
        <PanelCard
            title="Hypothesis"
            action={
                <Button size="icon-xs" aria-label="Edit hypothesis" tooltip="Edit hypothesis">
                    <IconPencil />
                </Button>
            }
        >
            <Text size="xs" render={<p className="m-0 line-clamp-4 @7xl/main-content:line-clamp-none" />}>
                {EXPERIMENT.hypothesis}
            </Text>
        </PanelCard>
    )
}

function AboutPanel({ status }: { status: PrototypeStatus }): JSX.Element {
    const dates =
        status === PROTOTYPE_STATUS.draft
            ? 'Not started'
            : status === PROTOTYPE_STATUS.complete
              ? `${EXPERIMENT.startDate} → ${EXPERIMENT.endDate}`
              : `${EXPERIMENT.startDate} → now`
    const rows: [string, React.ReactNode][] = [
        [
            'Flag',
            <span key="flag" className="flex min-w-0 items-center gap-1">
                <span className="truncate font-mono">{EXPERIMENT.flagKey}</span>
                <IconCopy className="shrink-0 text-muted-foreground" />
            </span>,
        ],
        ['Statistics', `${EXPERIMENT.statsMethod} · ${EXPERIMENT.confidence}`],
        ['Dates', dates],
        ['Owner', EXPERIMENT.owner],
    ]
    return (
        <PanelCard title="About">
            <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                {rows.map(([label, value]) => (
                    <div key={label} className="contents">
                        <Text size="xs" variant="muted" render={<dt />}>
                            {label}
                        </Text>
                        <Text size="xs" render={<dd className="m-0 min-w-0 truncate" />}>
                            {value}
                        </Text>
                    </div>
                ))}
            </dl>
        </PanelCard>
    )
}

function ContextPanels({ status }: { status: PrototypeStatus }): JSX.Element {
    return (
        <aside
            className={cn(
                PANEL_GRID,
                status === PROTOTYPE_STATUS.draft && '@5xl/main-content:grid-cols-3',
                '@7xl/main-content:sticky @7xl/main-content:top-(--status-line-height) self-start'
            )}
        >
            <ExposuresPanel status={status} />
            {status !== PROTOTYPE_STATUS.draft && <HealthPanel status={status} />}
            <HypothesisPanel />
            <AboutPanel status={status} />
        </aside>
    )
}

const METRIC_ACTIONS = [
    { key: 'details', label: 'Details', icon: <IconGraph /> },
    { key: 'recordings', label: 'View recordings', icon: <IconRewindPlay /> },
    { key: 'breakdowns', label: 'Breakdowns', icon: <IconFilter /> },
    { key: 'edit', label: 'Edit metric', icon: <IconPencil /> },
    { key: 'move', label: 'Move', icon: <IconDrag /> },
] as const

/** Icon buttons when the row has room; one menu with text labels when it does not. */
function MetricActions(): JSX.Element {
    return (
        <>
            <div className="hidden items-center gap-0.5 @3xl/main-content:flex">
                {METRIC_ACTIONS.map((action) => (
                    <Button key={action.key} size="icon-sm" aria-label={action.label} tooltip={action.label}>
                        {action.icon}
                    </Button>
                ))}
            </div>
            <div className="@3xl/main-content:hidden">
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={<Button size="icon-sm" aria-label="Metric actions" tooltip="Metric actions" />}
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        {METRIC_ACTIONS.map((action) => (
                            <DropdownMenuItem key={action.key}>
                                {action.icon}
                                {action.label}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </>
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
    return (
        <section className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
                <Heading size="sm" render={<h2 className="m-0" />}>
                    {title}
                </Heading>
                <Button>Add metric</Button>
            </div>
            <Card size="sm" flush className="overflow-clip">
                <Table size="sm" fullWidth stickyHeader="page">
                    <TableHeader>
                        <TableRow>
                            <TableHead>Variant</TableHead>
                            {!isDraft && (
                                <>
                                    <TableHead align="right" className="hidden @md/main-content:table-cell">
                                        Value
                                    </TableHead>
                                    <TableHead align="right">Delta</TableHead>
                                    <TableHead align="right">Chance to win</TableHead>
                                    <TableHead expand className="hidden @4xl/main-content:table-cell">
                                        <span className="flex justify-between gap-2">
                                            <span>Delta over time</span>
                                            <span className="font-normal">
                                                Nov 3 to Nov 16 · ±{Math.round(limit * 100)}%
                                            </span>
                                        </span>
                                    </TableHead>
                                </>
                            )}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {metrics.map((metric, metricIndex) => (
                            <MetricRows
                                key={metric.name}
                                metric={metric}
                                index={metricIndex}
                                colors={colors}
                                limit={limit}
                                isDraft={isDraft}
                            />
                        ))}
                    </TableBody>
                </Table>
            </Card>
        </section>
    )
}

function MetricRows({
    metric,
    index,
    colors,
    limit,
    isDraft,
}: {
    metric: PrototypeMetric
    index: number
    colors: Record<string, string>
    limit: number
    isDraft: boolean
}): JSX.Element {
    return (
        <>
            <TableRow className="bg-muted">
                <TableCell colSpan={5}>
                    <div className="flex items-center gap-2">
                        <Text size="xs" weight="semibold" render={<span className="min-w-0 truncate" />}>
                            {index + 1}. {metric.name}
                        </Text>
                        <Badge>{metric.kind}</Badge>
                        <div className="ml-auto">{!isDraft && <MetricActions />}</div>
                    </div>
                </TableCell>
            </TableRow>
            {isDraft ? (
                <TableRow>
                    <TableCell colSpan={5}>
                        <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
                            {metric.variants.map(({ key }) => (
                                <span key={key} className="flex items-center gap-2">
                                    <VariantDot color={colors[key]} />
                                    <span className="font-mono text-xs">{key}</span>
                                </span>
                            ))}
                            <Text size="xs" variant="muted" render={<span className="ml-auto" />}>
                                Results show after launch
                            </Text>
                        </span>
                    </TableCell>
                </TableRow>
            ) : (
                metric.variants.map((variant, variantIndex) => {
                    const significant =
                        variant.interval !== null && (variant.interval[0] > 0 || variant.interval[1] < 0)
                    return (
                        <TableRow key={variant.key} style={{ height: ROW_HEIGHT }}>
                            <TableCell>
                                <span className="flex items-center gap-2 whitespace-nowrap">
                                    <VariantDot color={colors[variant.key]} />
                                    <span className="font-mono text-xs">{variant.key}</span>
                                </span>
                            </TableCell>
                            <TableCell
                                align="right"
                                className="hidden whitespace-nowrap tabular-nums @md/main-content:table-cell"
                            >
                                <Text size="xs" render={<span className="block" />}>
                                    {variant.value}
                                </Text>
                                <Text size="xxs" variant="muted" render={<span className="block" />}>
                                    {variant.detail}
                                </Text>
                            </TableCell>
                            <TableCell align="right" className="tabular-nums">
                                <Text
                                    size="xs"
                                    weight={significant ? 'semibold' : 'normal'}
                                    render={
                                        <span
                                            className={cn(
                                                significant &&
                                                    variant.delta !== null &&
                                                    variant.delta > 0 &&
                                                    'text-success-foreground',
                                                significant &&
                                                    variant.delta !== null &&
                                                    variant.delta < 0 &&
                                                    'text-destructive-foreground',
                                                !significant && 'text-muted-foreground'
                                            )}
                                        />
                                    }
                                >
                                    {variant.delta === null ? 'Baseline' : formatDelta(variant.delta)}
                                </Text>
                            </TableCell>
                            <TableCell align="right" className="tabular-nums">
                                <Text size="xs" render={<span />}>
                                    {variant.chanceToWin === null ? '' : formatChance(variant.chanceToWin)}
                                </Text>
                            </TableCell>
                            {variantIndex === 0 && (
                                <TableCell
                                    rowSpan={metric.variants.length}
                                    className="hidden border-l border-border @4xl/main-content:table-cell"
                                >
                                    <PrototypeTrendChart
                                        trends={metricTrends(metric)}
                                        colors={colors}
                                        limit={limit}
                                        height={metric.variants.length * ROW_HEIGHT - 12}
                                        showValueAxis="yes"
                                    />
                                </TableCell>
                            )}
                        </TableRow>
                    )
                })
            )}
        </>
    )
}

function ResultsTab({ status }: { status: PrototypeStatus }): JSX.Element {
    return (
        <div className="grid grid-cols-1 gap-4 pt-3 @7xl/main-content:grid-cols-[minmax(0,1fr)_--spacing(80)]">
            <div className="@7xl/main-content:col-start-2 @7xl/main-content:row-start-1">
                <ContextPanels status={status} />
            </div>
            <div className="flex min-w-0 flex-col gap-4 @7xl/main-content:col-start-1 @7xl/main-content:row-start-1">
                <MetricsTable title="Primary metrics" metrics={PRIMARY_METRICS} status={status} />
                <MetricsTable title="Secondary metrics" metrics={SECONDARY_METRICS} status={status} />
            </div>
        </div>
    )
}

export function QuillPrototypeExperimentPageV6({
    status,
    shell,
    progress,
}: {
    status: PrototypeStatus
    shell: ShellState
    progress: RunProgress
}): JSX.Element {
    const [compact, setCompact] = useState(false)
    const [lineRef, lineHeight] = useHeight()
    const tabs = [
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
        <div data-quill className="flex h-screen bg-background text-foreground">
            <FakeShell shell={shell} />
            <main className="@container/main-content flex min-w-0 flex-1 flex-col">
                {shell === SHELL_STATE.phone && <FakePhoneHeader />}
                <QuillSceneHeader
                    icon={<IconFlask />}
                    title={<SceneTitle />}
                    actions={<SceneActions status={status} />}
                />
                <div
                    data-attr="prototype-scroll"
                    className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 pb-3"
                    style={
                        {
                            '--quill-table-sticky-top': `${lineHeight}px`,
                            '--status-line-height': `${lineHeight + 12}px`,
                        } as React.CSSProperties
                    }
                    onScroll={(event) => setCompact(event.currentTarget.scrollTop > COMPACT_AFTER_PX)}
                >
                    <MetaLine status={status} progress={progress} compact={compact} lineRef={lineRef} />
                    <Verdict status={status} progress={progress} />
                    <Tabs defaultValue="results">
                        <TabsList variant="line">
                            {tabs.map(([key, label]) => (
                                <TabsTrigger key={key} value={key}>
                                    {label}
                                </TabsTrigger>
                            ))}
                        </TabsList>
                        <TabsContent value="results">
                            <ResultsTab status={status} />
                        </TabsContent>
                    </Tabs>
                </div>
            </main>
        </div>
    )
}
