/** Scratch prototype v15: v13 with a switch for how metric results are drawn. Not committed. */
import { DndContext, type DragEndEvent, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import {
    SortableContext,
    arrayMove,
    rectSortingStrategy,
    sortableKeyboardCoordinates,
    useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'

import {
    IconCheckCircle,
    IconCircleDashed,
    IconCopy,
    IconEllipsis,
    IconFlag,
    IconChevronDown,
    IconDrag,
    IconExternal,
    IconFilter,
    IconFlask,
    IconGear,
    IconGraph,
    IconHide,
    IconPlus,
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
    Avatar,
    AvatarFallback,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Field,
    FieldLabel,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Progress,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Switch,
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
    ToastProvider,
    anchoredToast,
    cn,
    toast,
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
import {
    CandlestickChart,
    METRIC_VIEW,
    type MetricView,
    MetricViewSwitch,
    SECTION_CHART_VIEWS,
    SectionChart,
} from './PrototypeMetricViews'
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
            <span className="hidden items-center @lg/main-content:flex">
                <Separator orientation="vertical" className="mx-2 h-4" />
                {['File', 'Edit', 'Help'].map((menu) => (
                    <Button key={menu} size="sm">
                        {menu}
                    </Button>
                ))}
            </span>
        </>
    )
}

/** The status line wraps on a narrow scene, so the sticky table header and right column read its height. */
function useHeight<T extends HTMLElement>(): [React.RefObject<T>, number] {
    const ref = useRef<T>(null)
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
                <div className="hidden items-center gap-2 @lg/main-content:flex">
                    <Progress value={targetReached ? 100 : 64} variant="success" className="w-16" />
                    <Text size="xs" render={<span />}>
                        {targetReached ? 'Target reached' : '~5 days left'}
                    </Text>
                </div>
            )}
            {isRunning && (
                <Text size="xs" variant="muted" render={<span className="hidden @lg/main-content:inline" />}>
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
                <span className="hidden min-w-0 items-center gap-3 @lg/main-content:flex">
                    <Separator orientation="vertical" className="h-4" />
                    <Text size="xs" render={<span className="min-w-0 truncate" />}>
                        <span className="font-mono">one-page</span> {targetReached ? 'won' : 'leads'} on Checkout
                        completed <span className="text-success-foreground">+8.4%</span>
                    </Text>
                </span>
            )}
            <div className="ml-auto flex items-center gap-3">
                {isRunning && (
                    <Text
                        size="xs"
                        variant="muted"
                        render={<span className="hidden whitespace-nowrap @lg/main-content:inline" />}
                    >
                        Refreshed 9 minutes ago ·{' '}
                        <Button variant="link" size="inline">
                            Refresh
                        </Button>
                    </Text>
                )}
                {isRunning && <StatusLineMenu targetReached={targetReached} />}
            </div>
        </div>
    )
}

/** Phone only: what the status line drops to stay on one row. */
function StatusLineMenu({ targetReached }: { targetReached: boolean }): JSX.Element {
    return (
        <div className="@lg/main-content:hidden">
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={<Button size="icon-sm" aria-label="Experiment status" tooltip="Experiment status" />}
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuItem disabled>{targetReached ? 'Target reached' : '~5 days left'}</DropdownMenuItem>
                    <DropdownMenuItem disabled>{EXPERIMENT.startDate} → now</DropdownMenuItem>
                    <DropdownMenuItem disabled>Refreshed 9 minutes ago</DropdownMenuItem>
                    <DropdownMenuItem>Refresh results</DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
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
                        <Button variant={targetReached ? 'primary' : 'outline'} data-attr="summary-release-variant">
                            Release one-page variant
                        </Button>
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
                            ? 'Target reached. We recommend ending the experiment and keeping one-page.'
                            : 'About 5 days left. Ending the experiment now stops it before it reaches its running time.'}
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
                    compact-cart did not win: Items per order went down 5.2%. End the experiment with one-page as the
                    variant to keep to serve it to 100% of users through the flag {EXPERIMENT.flagKey}.
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

type DragHandleProps = Pick<ReturnType<typeof useSortable>, 'attributes' | 'listeners' | 'setActivatorNodeRef'>

/** Set by SortablePanel, so each panel card renders its own drag handle without knowing it is sortable. */
const DragHandleContext = createContext<DragHandleProps | null>(null)

function PanelDragHandle({ title }: { title: string }): JSX.Element | null {
    const handle = useContext(DragHandleContext)
    if (!handle) {
        return null
    }
    return (
        <Button
            ref={handle.setActivatorNodeRef}
            size="icon-xs"
            aria-label={`Move ${title.toLowerCase()} card`}
            tooltip="Drag to reorder"
            className="-ml-1 cursor-grab touch-none text-muted-foreground active:cursor-grabbing"
            data-attr="panel-drag-handle"
            {...handle.attributes}
            {...handle.listeners}
        >
            <IconDrag />
        </Button>
    )
}

/** Set by ContextPanels, so each panel card renders its own hide button without knowing which card it is. */
const HidePanelContext = createContext<(() => void) | null>(null)

function PanelHideButton({ title }: { title: string }): JSX.Element | null {
    const hide = useContext(HidePanelContext)
    if (!hide) {
        return null
    }
    return (
        <Button
            size="icon-xs"
            aria-label={`Hide ${title.toLowerCase()} card`}
            tooltip="Hide card"
            className="text-muted-foreground opacity-0 transition-opacity group-hover/panel:opacity-100 focus-visible:opacity-100"
            data-attr="panel-hide"
            onClick={hide}
        >
            <IconHide />
        </Button>
    )
}

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
        <Card size="sm" className="group/panel">
            <CardHeader>
                <CardTitle>
                    <span className="flex items-center gap-1">
                        <PanelDragHandle title={title} />
                        <Text size="xxs" variant="muted" weight="medium" render={<span className="uppercase" />}>
                            {title}
                        </Text>
                    </span>
                </CardTitle>
                <CardAction className="flex items-center gap-1">
                    <PanelHideButton title={title} />
                    {action}
                </CardAction>
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

const CONFIDENCE_ITEMS = [
    { label: '90%', value: '90' },
    { label: '95%', value: '95' },
    { label: '99%', value: '99' },
]

const METHOD_LABEL = { bayesian: 'Bayesian', frequentist: 'Frequentist' } as const
type StatsMethod = keyof typeof METHOD_LABEL

/** A settings value that opens its editor in a popover. */
function SettingValueButton({
    label,
    children,
    attr,
}: {
    label: string
    children: React.ReactNode
    attr: string
}): JSX.Element {
    return (
        <Popover>
            <PopoverTrigger
                render={
                    <Button
                        size="sm"
                        className="-ml-2 max-w-full justify-start"
                        aria-label={`Edit ${label.toLowerCase()}`}
                        data-attr={attr}
                    />
                }
            >
                <span className="truncate">{label}</span>
                <IconChevronDown className="text-muted-foreground" />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-72">
                {children}
            </PopoverContent>
        </Popover>
    )
}

function StatisticsEditor({
    method,
    confidence,
    onSave,
}: {
    method: StatsMethod
    confidence: string
    onSave: (method: StatsMethod, confidence: string) => void
}): JSX.Element {
    const [draftMethod, setDraftMethod] = useState<StatsMethod>(method)
    const [draftConfidence, setDraftConfidence] = useState(confidence)
    return (
        <div className="flex flex-col gap-3">
            <Heading size="sm" render={<h3 className="m-0" />}>
                Statistics
            </Heading>
            <RadioGroup value={draftMethod} onValueChange={(value) => setDraftMethod(value as StatsMethod)}>
                {(Object.keys(METHOD_LABEL) as StatsMethod[]).map((key) => (
                    <div key={key} className="flex items-center gap-2">
                        <RadioGroupItem value={key} id={`stats-${key}`} />
                        <Label htmlFor={`stats-${key}`}>{METHOD_LABEL[key]}</Label>
                    </div>
                ))}
            </RadioGroup>
            <Field>
                <FieldLabel>{draftMethod === 'bayesian' ? 'Credible interval' : 'Confidence level'}</FieldLabel>
                <Select
                    items={CONFIDENCE_ITEMS}
                    value={draftConfidence}
                    onValueChange={(value) => setDraftConfidence(String(value))}
                >
                    <SelectTrigger render={<Button variant="outline" className="w-full" />}>
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {CONFIDENCE_ITEMS.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                                {item.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </Field>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Changing statistics recalculates every metric.
            </Text>
            <Button variant="primary" onClick={() => onSave(draftMethod, draftConfidence)}>
                Save and recalculate
            </Button>
        </div>
    )
}

function SettingsPanel({ status, progress }: { status: PrototypeStatus; progress: RunProgress }): JSX.Element {
    const [method, setMethod] = useState<StatsMethod>('bayesian')
    const [confidence, setConfidence] = useState('95')
    const [cuped, setCuped] = useState(true)
    const isDraft = status === PROTOTYPE_STATUS.draft
    const dates =
        status === PROTOTYPE_STATUS.draft
            ? 'Not started'
            : status === PROTOTYPE_STATUS.complete
              ? `${EXPERIMENT.startDate} → ${EXPERIMENT.endDate}`
              : `${EXPERIMENT.startDate} → now`

    const toggleCuped = (checked: boolean): void => {
        setCuped(checked)
        toast({
            title: checked ? 'CUPED turned on' : 'CUPED turned off',
            description: isDraft ? undefined : 'Metrics recalculate with the new setting.',
            action: { label: 'Undo', onClick: () => setCuped(!checked) },
        })
    }

    const rows: [string, React.ReactNode][] = [
        [
            'Feature flag',
            <span key="flag" className="flex min-w-0 items-center gap-0.5">
                <span className="truncate font-mono">{EXPERIMENT.flagKey}</span>
                <Button
                    size="icon-xs"
                    aria-label="Copy flag key"
                    tooltip="Copy flag key"
                    data-attr="settings-copy-flag"
                    onClick={(event) => anchoredToast({ title: 'Copied', anchor: event.currentTarget })}
                >
                    <IconCopy />
                </Button>
                <Button size="icon-xs" aria-label="Open feature flag" tooltip="Open feature flag">
                    <IconExternal />
                </Button>
            </span>,
        ],
        [
            'Statistics',
            <SettingValueButton
                key="stats"
                label={`${METHOD_LABEL[method]} · ${confidence}%`}
                attr="settings-statistics"
            >
                <StatisticsEditor
                    method={method}
                    confidence={confidence}
                    onSave={(nextMethod, nextConfidence) => {
                        setMethod(nextMethod)
                        setConfidence(nextConfidence)
                        toast({ title: 'Statistics saved', description: 'Metrics are recalculating.' })
                    }}
                />
            </SettingValueButton>,
        ],
        [
            'CUPED',
            <span key="cuped" className="flex items-center gap-2">
                <Switch
                    size="sm"
                    checked={cuped}
                    onCheckedChange={toggleCuped}
                    aria-label="CUPED"
                    data-attr="settings-cuped"
                />
                <Text size="xs" variant="muted" render={<span />}>
                    {cuped ? 'On' : 'Off'}
                </Text>
            </span>,
        ],
        [
            'Running time',
            <span key="running-time" className="flex items-center gap-0.5">
                {status === PROTOTYPE_STATUS.draft
                    ? '~14 days estimated'
                    : progress === RUN_PROGRESS.targetReached
                      ? 'Target reached'
                      : '~5 days left'}
                {/* Opens the existing Running time modal (RunningTimeConfigModal). */}
                <Button
                    size="icon-xs"
                    aria-label="Edit running time"
                    tooltip="Edit running time"
                    data-attr="settings-running-time"
                >
                    <IconPencil />
                </Button>
            </span>,
        ],
        [
            'Variants',
            <Button key="variants" variant="link" size="sm" className="-ml-2">
                3, equal split
            </Button>,
        ],
        ['Dates', <span key="dates">{dates}</span>],
        [
            'Created by',
            <span key="owner" className="flex items-center gap-1.5">
                <Avatar className="size-5">
                    <AvatarFallback>{EXPERIMENT.ownerInitial}</AvatarFallback>
                </Avatar>
                {EXPERIMENT.owner}
            </span>,
        ],
    ]
    return (
        <PanelCard
            title="Experiment settings"
            action={
                <Button size="icon-xs" aria-label="All settings" tooltip="All settings">
                    <IconGear />
                </Button>
            }
        >
            <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-0.5">
                {rows.map(([label, value]) => (
                    <div key={label} className="contents">
                        <Text size="xs" variant="muted" render={<dt className="whitespace-nowrap" />}>
                            {label}
                        </Text>
                        <Text size="xs" render={<dd className="m-0 flex min-h-7 min-w-0 items-center" />}>
                            {value}
                        </Text>
                    </div>
                ))}
            </dl>
        </PanelCard>
    )
}

export const PANEL_KEYS = {
    exposures: 'exposures',
    health: 'health',
    hypothesis: 'hypothesis',
    settings: 'settings',
} as const
export type PanelKey = (typeof PANEL_KEYS)[keyof typeof PANEL_KEYS]
export const DEFAULT_PANEL_ORDER: PanelKey[] = ['exposures', 'health', 'hypothesis', 'settings']

const PANEL_TITLES: Record<PanelKey, string> = {
    exposures: 'Exposures',
    health: 'Health',
    hypothesis: 'Hypothesis',
    settings: 'Experiment settings',
}

/** Lists the hidden cards so the user can bring each one back, in the order the cards had before. */
function HiddenCardsMenu({
    hidden,
    onShow,
    onShowAll,
    trigger,
}: {
    hidden: PanelKey[]
    onShow: (key: PanelKey) => void
    onShowAll: () => void
    trigger: React.ReactElement
}): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={trigger} />
            <DropdownMenuContent align="end" className="min-w-52">
                {hidden.map((key) => (
                    <DropdownMenuItem key={key} onClick={() => onShow(key)} data-attr="panel-show">
                        <IconPlus />
                        {PANEL_TITLES[key]}
                    </DropdownMenuItem>
                ))}
                {hidden.length > 1 && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={onShowAll} data-attr="panel-show-all">
                            Show all cards
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function SortablePanel({ id, children }: { id: PanelKey; children: React.ReactNode }): JSX.Element {
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
        id,
    })
    return (
        <div
            ref={setNodeRef}
            className={cn('min-w-0', isDragging && 'relative z-30 rounded-lg shadow-lg ring-2 ring-ring')}
            style={{ transform: CSS.Translate.toString(transform), transition }}
        >
            <DragHandleContext.Provider value={{ attributes, listeners, setActivatorNodeRef }}>
                {children}
            </DragHandleContext.Provider>
        </div>
    )
}

function ContextPanels({
    status,
    progress,
    order,
    onOrderChange,
    hidden,
    onHide,
    onShow,
    onShowAll,
}: {
    status: PrototypeStatus
    progress: RunProgress
    order: PanelKey[]
    onOrderChange: (order: PanelKey[]) => void
    hidden: PanelKey[]
    onHide: (key: PanelKey) => void
    onShow: (key: PanelKey) => void
    onShowAll: () => void
}): JSX.Element {
    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )
    const visible = order.filter((key) => !hidden.includes(key))
    const panels: Record<PanelKey, JSX.Element> = {
        exposures: <ExposuresPanel status={status} />,
        health: <HealthPanel status={status} />,
        hypothesis: <HypothesisPanel />,
        settings: <SettingsPanel status={status} progress={progress} />,
    }
    const onDragEnd = ({ active, over }: DragEndEvent): void => {
        if (!over || active.id === over.id) {
            return
        }
        onOrderChange(arrayMove(order, order.indexOf(active.id as PanelKey), order.indexOf(over.id as PanelKey)))
    }
    return (
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
            <SortableContext items={visible} strategy={rectSortingStrategy}>
                <aside
                    className={cn(
                        PANEL_GRID,
                        status === PROTOTYPE_STATUS.draft && '@5xl/main-content:grid-cols-3',
                        '@7xl/main-content:sticky @7xl/main-content:top-(--status-line-height) self-start'
                    )}
                >
                    {visible.map((key) => (
                        <SortablePanel key={key} id={key}>
                            <HidePanelContext.Provider value={() => onHide(key)}>
                                {panels[key]}
                            </HidePanelContext.Provider>
                        </SortablePanel>
                    ))}
                    {hidden.length > 0 && (
                        <HiddenCardsMenu
                            hidden={hidden}
                            onShow={onShow}
                            onShowAll={onShowAll}
                            trigger={
                                <Button
                                    variant="outline"
                                    className="h-auto min-h-10 w-full justify-center border-dashed text-muted-foreground"
                                    data-attr="panel-add-card"
                                >
                                    <IconPlus />
                                    {`Add card (${hidden.length} hidden)`}
                                </Button>
                            }
                        />
                    )}
                </aside>
            </SortableContext>
        </DndContext>
    )
}

/** The strongest significant change in a metric, said in words for screens without the trend chart. */
function metricOutcome(metric: PrototypeMetric): { text: string; tone: 'up' | 'down' | 'none' } {
    const significant = metric.variants.filter(
        (variant) =>
            variant.delta !== null && variant.interval !== null && (variant.interval[0] > 0 || variant.interval[1] < 0)
    )
    if (significant.length === 0) {
        return { text: 'No significant change', tone: 'none' }
    }
    const strongest = significant.reduce((best, variant) =>
        Math.abs(variant.delta ?? 0) > Math.abs(best.delta ?? 0) ? variant : best
    )
    const delta = strongest.delta ?? 0
    return { text: `${strongest.key} ${formatDelta(delta)}, significant`, tone: delta > 0 ? 'up' : 'down' }
}

const METRIC_ACTIONS = [
    { key: 'details', label: 'Details', icon: <IconGraph /> },
    { key: 'recordings', label: 'View recordings', icon: <IconRewindPlay /> },
    { key: 'breakdowns', label: 'Breakdown by', icon: <IconFilter /> },
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

/** Height of the sticky metric type heading ("Primary metrics"), so the column names can sit below it. */
const TYPE_HEADING_PX = 40

function MetricsTable({
    title,
    metrics,
    status,
    stickyTop,
    view,
}: {
    title: string
    metrics: PrototypeMetric[]
    status: PrototypeStatus
    stickyTop: number
    view: MetricView
}): JSX.Element {
    const colors = useVariantColors()
    const rowChart = !SECTION_CHART_VIEWS.includes(view)
    const isDraft = status === PROTOTYPE_STATUS.draft
    const limit = axisLimit(metrics)
    const [headRef, headHeight] = useHeight<HTMLTableSectionElement>()
    const columnsTop = stickyTop + TYPE_HEADING_PX
    return (
        <section
            className="flex flex-col"
            style={{ '--quill-table-sticky-top': `${columnsTop}px` } as React.CSSProperties}
        >
            <div
                className="sticky z-15 -mx-1 flex items-center justify-between bg-background px-1"
                style={{ top: stickyTop, height: TYPE_HEADING_PX }}
            >
                <Heading size="sm" render={<h2 className="m-0" />}>
                    {title}
                </Heading>
                <Button>{title === 'Primary metrics' ? 'Add primary metric' : 'Add secondary metric'}</Button>
            </div>
            {!isDraft && <SectionChart view={view} title={title} metrics={metrics} colors={colors} limit={limit} />}
            <Card size="sm" flush className="overflow-clip">
                <Table size="sm" fullWidth stickyHeader="page">
                    <TableHeader ref={headRef}>
                        <TableRow>
                            <TableHead>Variant</TableHead>
                            {!isDraft && (
                                <>
                                    <TableHead align="right" className="hidden @md/main-content:table-cell">
                                        Value
                                    </TableHead>
                                    <TableHead align="right">Delta</TableHead>
                                    <TableHead align="right">Chance to win</TableHead>
                                    {rowChart && (
                                        <TableHead expand className="hidden @4xl/main-content:table-cell">
                                            {view === METRIC_VIEW.candlestick ? (
                                                <span className="flex justify-between gap-2">
                                                    <span>Delta and interval</span>
                                                    <span className="font-normal">Box 50% · whiskers 95%</span>
                                                </span>
                                            ) : (
                                                <span className="flex justify-between gap-2">
                                                    <span>Delta over time</span>
                                                    <span className="font-normal">
                                                        Nov 3 to Nov 16 · ±{Math.round(limit * 100)}%
                                                    </span>
                                                </span>
                                            )}
                                        </TableHead>
                                    )}
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
                                stickyTop={columnsTop + headHeight}
                                view={view}
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
    stickyTop,
    view,
}: {
    metric: PrototypeMetric
    index: number
    colors: Record<string, string>
    limit: number
    isDraft: boolean
    stickyTop: number
    view: MetricView
}): JSX.Element {
    const outcome = metricOutcome(metric)
    const rowChart = !SECTION_CHART_VIEWS.includes(view)
    return (
        <>
            <TableRow>
                {/* Each metric row sticks below the column names until the next metric row pushes it out. */}
                <TableCell
                    colSpan={5}
                    className="sticky z-10 border-b border-border bg-muted"
                    style={{ top: stickyTop }}
                >
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <Text size="xs" weight="semibold" render={<span className="min-w-0 truncate" />}>
                            {index + 1}. {metric.name}
                        </Text>
                        <Badge>{metric.kind}</Badge>
                        <div className="ml-auto">{!isDraft && <MetricActions />}</div>
                        {!isDraft && (
                            <Text
                                size="xs"
                                render={
                                    <span
                                        className={cn(
                                            'basis-full @4xl/main-content:hidden',
                                            outcome.tone === 'up' && 'text-success-foreground',
                                            outcome.tone === 'down' && 'text-destructive-foreground',
                                            outcome.tone === 'none' && 'text-muted-foreground'
                                        )}
                                    />
                                }
                            >
                                {outcome.text}
                            </Text>
                        )}
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
                            {rowChart && variantIndex === 0 && (
                                <TableCell
                                    rowSpan={metric.variants.length}
                                    className="hidden border-l border-border @4xl/main-content:table-cell"
                                >
                                    {view === METRIC_VIEW.candlestick ? (
                                        <CandlestickChart
                                            metric={metric}
                                            height={metric.variants.length * ROW_HEIGHT - 12}
                                        />
                                    ) : (
                                        <PrototypeTrendChart
                                            trends={metricTrends(metric)}
                                            colors={colors}
                                            limit={limit}
                                            height={metric.variants.length * ROW_HEIGHT - 12}
                                            showValueAxis="yes"
                                        />
                                    )}
                                </TableCell>
                            )}
                        </TableRow>
                    )
                })
            )}
        </>
    )
}

function ResultsTab({
    status,
    progress,
    stickyTop,
    panelOrder,
    hiddenPanels,
    metricView,
}: {
    status: PrototypeStatus
    progress: RunProgress
    stickyTop: number
    panelOrder: PanelKey[]
    hiddenPanels: PanelKey[]
    metricView: MetricView
}): JSX.Element {
    const [view, setView] = useState<MetricView>(metricView)
    const [order, setOrder] = useState<PanelKey[]>(panelOrder)
    const [hidden, setHidden] = useState<PanelKey[]>(hiddenPanels)
    /** Health has nothing to say before launch, so a draft never lists it, hidden or not. */
    const available = order.filter((key) => key !== PANEL_KEYS.health || status !== PROTOTYPE_STATUS.draft)
    const hiddenAvailable = available.filter((key) => hidden.includes(key))
    const allHidden = hiddenAvailable.length === available.length
    const show = (key: PanelKey): void => setHidden((current) => current.filter((item) => item !== key))
    const showAll = (): void => setHidden([])
    const hide = (key: PanelKey): void => {
        setHidden((current) => [...current, key])
        toast({
            title: `${PANEL_TITLES[key]} card hidden`,
            description: 'Add it back from Add card.',
            action: { label: 'Undo', onClick: () => show(key) },
        })
    }
    return (
        <div
            className={cn(
                'grid grid-cols-1 gap-4 pt-3',
                !allHidden && '@7xl/main-content:grid-cols-[minmax(0,1fr)_--spacing(80)]'
            )}
        >
            {!allHidden && (
                <div className="@7xl/main-content:col-start-2 @7xl/main-content:row-start-1">
                    <ContextPanels
                        status={status}
                        progress={progress}
                        order={available}
                        onOrderChange={setOrder}
                        hidden={hiddenAvailable}
                        onHide={hide}
                        onShow={show}
                        onShowAll={showAll}
                    />
                </div>
            )}
            <div className="flex min-w-0 flex-col gap-4 @7xl/main-content:col-start-1 @7xl/main-content:row-start-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    {status !== PROTOTYPE_STATUS.draft && <MetricViewSwitch view={view} onChange={setView} />}
                    {allHidden && (
                        <div className="ml-auto flex items-center justify-end gap-2">
                            <Text size="xs" variant="muted">
                                All cards are hidden
                            </Text>
                            <HiddenCardsMenu
                                hidden={hiddenAvailable}
                                onShow={show}
                                onShowAll={showAll}
                                trigger={
                                    <Button variant="outline" size="sm" data-attr="panel-add-card">
                                        <IconPlus />
                                        Add card
                                    </Button>
                                }
                            />
                        </div>
                    )}
                </div>
                <MetricsTable
                    title="Primary metrics"
                    metrics={PRIMARY_METRICS}
                    status={status}
                    stickyTop={stickyTop}
                    view={view}
                />
                <MetricsTable
                    title="Secondary metrics"
                    metrics={SECONDARY_METRICS}
                    status={status}
                    stickyTop={stickyTop}
                    view={view}
                />
            </div>
        </div>
    )
}

export function QuillPrototypeExperimentPageV15({
    status,
    shell,
    progress,
    panelOrder = DEFAULT_PANEL_ORDER,
    hiddenPanels = [],
    metricView = METRIC_VIEW.perMetric,
}: {
    status: PrototypeStatus
    shell: ShellState
    progress: RunProgress
    panelOrder?: PanelKey[]
    hiddenPanels?: PanelKey[]
    metricView?: MetricView
}): JSX.Element {
    const [compact, setCompact] = useState(false)
    const [lineRef, lineHeight] = useHeight<HTMLDivElement>()
    const tabs = [
        ['results', 'Metrics'],
        ['health', 'Health'],
        ['recordings', 'Recordings'],
        ['feedback', 'User feedback'],
        ['settings', 'Settings'],
        ['variants', 'Variants'],
        ['code', 'Code'],
        ['history', 'History'],
    ] as const
    return (
        <ToastProvider timeout={20000}>
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
                        className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 pb-3 *:shrink-0"
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
                                <ResultsTab
                                    status={status}
                                    progress={progress}
                                    stickyTop={lineHeight}
                                    panelOrder={panelOrder}
                                    hiddenPanels={hiddenPanels}
                                    metricView={metricView}
                                />
                            </TabsContent>
                        </Tabs>
                    </div>
                </main>
            </div>
        </ToastProvider>
    )
}
