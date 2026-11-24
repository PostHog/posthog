/** Scratch prototype v20: v18 with more white space and fewer items on the page. Not committed. */
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
    IconSparkles,
    IconWarning,
    IconRefresh,
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
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
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
import { TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

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
    MetricRowChart,
    RESULT_CHART,
    RESULT_LAYOUT,
    type ResultChart,
    type ResultLayout,
    SectionResultChart,
} from './PrototypeMetricViewsV16'
import { CompactResultViewSwitch } from './PrototypeResultViewSwitchV20'
import { metricTrends } from './prototypeTimeseries'
import { PrototypeTrendChart } from './PrototypeTrendChart'

export const SHELL_STATE = { sidebarOpen: 'sidebar-open', sidebarClosed: 'sidebar-closed', phone: 'phone' } as const
export type ShellState = (typeof SHELL_STATE)[keyof typeof SHELL_STATE]

export const RUN_PROGRESS = { inProgress: 'in-progress', targetReached: 'target-reached' } as const
export type RunProgress = (typeof RUN_PROGRESS)[keyof typeof RUN_PROGRESS]

/** Scroll distance after which the summary has left the view and the status line carries its short form. */
const COMPACT_AFTER_PX = 200

const ROW_HEIGHT = 52

export function useVariantColors(): Record<string, string> {
    const theme = useChartTheme()
    return useMemo(
        () => Object.fromEntries(VARIANTS.map((key, index) => [key, theme.colors[index % theme.colors.length]])),
        [theme]
    )
}

export function axisLimit(metrics: PrototypeMetric[]): number {
    const widest = Math.max(
        ...metrics.flatMap((metric) =>
            metric.variants.flatMap((variant) => (variant.interval ? variant.interval.map(Math.abs) : [0]))
        )
    )
    return Math.ceil(widest * 20) / 20
}

export function formatDelta(delta: number): string {
    return `${delta > 0 ? '+' : ''}${(delta * 100).toFixed(1)}%`
}

export function formatChance(chance: number): string {
    if (chance >= 0.995) {
        return '> 99%'
    }
    if (chance <= 0.005) {
        return '< 1%'
    }
    return `${Math.round(chance * 100)}%`
}

export function VariantDot({ color }: { color: string }): JSX.Element {
    return <span className="inline-block size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
}

export function StatusBadge({ status }: { status: PrototypeStatus }): JSX.Element {
    const variant = { draft: 'default', running: 'success', paused: 'warning', complete: 'completed' } as const
    const label = { draft: 'Draft', running: 'Running', paused: 'Paused', complete: 'Complete' }
    return <Badge variant={variant[status]}>{label[status]}</Badge>
}

/** Placeholder for the rail and the Products sidebar, so the scene gets its real width. */
export function FakeShell({ shell }: { shell: ShellState }): JSX.Element | null {
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
export function FakePhoneHeader(): JSX.Element {
    return (
        <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-chrome px-3">
            <div className="size-7 rounded-md bg-fill-hover" />
            <div className="h-4 w-28 rounded-sm bg-fill-hover" />
            <div className="ml-auto size-7 rounded-md bg-fill-hover" />
        </div>
    )
}

export function SceneActions({ status }: { status: PrototypeStatus }): JSX.Element {
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

export function SceneTitle(): JSX.Element {
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
                'sticky top-0 z-20 flex flex-wrap items-center gap-x-4 gap-y-1 bg-background py-3',
                compact && 'border-b border-border shadow-sm'
            )}
            style={{ marginInline: '-2rem', paddingInline: '2rem' }}
        >
            <StatusBadge status={status} />
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
                    <Button
                        size="icon-sm"
                        aria-label="Refresh results"
                        tooltip="Refreshed 9 minutes ago. Click to refresh."
                        className="hidden text-muted-foreground @lg/main-content:inline-flex"
                    >
                        <IconRefresh />
                    </Button>
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

/**
 * The result in plain text, without a card frame. The status line already says "Target reached",
 * and the metric table shows the compact-cart loss, so neither repeats here.
 */
function SummaryReport({ progress }: { progress: RunProgress }): JSX.Element {
    const targetReached = progress === RUN_PROGRESS.targetReached
    return (
        <section className="flex flex-col gap-5 pt-2" data-attr="summary">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex max-w-3xl flex-col gap-1.5">
                    <Heading size="lg" render={<h2 className="m-0" />}>
                        <span className="font-mono">one-page</span> {targetReached ? 'won' : 'leads'} on Checkout
                        completed with <span className="text-success-foreground">+8.4%</span>
                    </Heading>
                    <Text size="sm" variant="muted" render={<p className="m-0" />}>
                        {targetReached
                            ? 'We recommend ending the experiment and keeping one-page.'
                            : 'About 5 days left. Ending the experiment now stops it before it reaches its running time.'}
                    </Text>
                </div>
                <Button variant={targetReached ? 'primary' : 'outline'} data-attr="summary-release-variant">
                    Release one-page variant
                </Button>
            </div>
            <div className="grid max-w-5xl grid-cols-1 gap-x-10 gap-y-3 @4xl/main-content:grid-cols-2">
                {REASONS.map((reason) => (
                    <div key={reason.title} className="flex items-start gap-2">
                        {reason.tone === 'good' ? (
                            <IconCheckCircle className="mt-0.5 shrink-0 text-success-foreground" />
                        ) : (
                            <IconWarning className="mt-0.5 shrink-0 text-warning-foreground" />
                        )}
                        <div className="flex flex-col gap-0.5">
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
        </section>
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

const WIZARD_COMMAND = 'npx @posthog/wizard'

/** Invented for the fake experiment: what a generated prompt could say, built from the flag and its variants. */
const WIZARD_PROMPT = `Add the PostHog feature flag "${EXPERIMENT.flagKey}" to the checkout. Use the PostHog SDK the project already has.

Variants:
- control: keep the current checkout.
- compact-cart: show the cart summary in a side panel during checkout.
- one-page: show cart, shipping and payment on one page.

Read the variant with posthog.getFeatureFlag("${EXPERIMENT.flagKey}") before the checkout renders, so each user sees one variant for the whole session. Do not rename or remove events the project already captures.`

const SUGGESTED_METRICS = [
    {
        key: 'checkout-steps',
        name: 'Checkout started to completed',
        kind: 'Funnel',
        role: 'Primary',
        reason: 'Measures the steps the one-page variant removes.',
    },
    {
        key: 'checkout-time',
        name: 'Time to complete checkout',
        kind: 'Mean',
        role: 'Primary',
        reason: 'Shows if a shorter checkout is also a faster one.',
    },
    {
        key: 'cart-abandoned',
        name: 'Cart abandoned',
        kind: 'Funnel',
        role: 'Secondary',
        reason: 'Catches users who leave before they pay.',
    },
    {
        key: 'refund-requested',
        name: 'Refund requested',
        kind: 'Funnel',
        role: 'Secondary',
        reason: 'Catches orders placed by mistake in a shorter flow.',
    },
] as const

const SETUP_REVIEW = [
    {
        tone: 'warning',
        title: 'No running time target',
        detail: 'Without one, the page cannot say when results are ready. At current traffic, 14 days gives 80% power for a 5% lift.',
    },
    {
        tone: 'warning',
        title: 'Items per order can move with order size',
        detail: 'A ratio metric is sensitive to a few large orders. Consider outlier handling for this metric.',
    },
    {
        tone: 'ok',
        title: 'Exposure criteria match the flag',
        detail: 'Users are counted when $feature_flag_called fires for new-checkout-flow.',
    },
] as const

function CopyButton({ text, label }: { text: string; label: string }): JSX.Element {
    return (
        <Button
            size="sm"
            variant="outline"
            onClick={(event) => {
                void navigator.clipboard?.writeText(text).catch(() => undefined)
                anchoredToast({ title: 'Copied', anchor: event.currentTarget })
            }}
        >
            <IconCopy />
            {label}
        </Button>
    )
}

/** The prompt PostHog AI writes for this flag, to run with Wizard or to paste into any coding agent. */
function WizardPromptDialog(): JSX.Element {
    return (
        <Dialog>
            <DialogTrigger render={<Button variant="outline" size="sm" data-attr="checklist-wizard-prompt" />}>
                <IconSparkles />
                Show Wizard prompt
            </DialogTrigger>
            <DialogContent className="max-w-xl">
                <DialogHeader>
                    <DialogTitle>Add the flag with Wizard</DialogTitle>
                    <DialogDescription>
                        Run Wizard in your project, or paste the prompt into your coding agent. The setup agent adds the
                        flag check for each variant.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1">
                        <Text size="xs" weight="medium">
                            Run in your project
                        </Text>
                        <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted px-3 py-2">
                            <code className="font-mono text-xs">{WIZARD_COMMAND}</code>
                            <CopyButton text={WIZARD_COMMAND} label="Copy" />
                        </div>
                    </div>
                    <div className="flex flex-col gap-1">
                        <Text size="xs" weight="medium">
                            Prompt
                        </Text>
                        <pre className="m-0 max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted px-3 py-2 font-mono text-xs">
                            {WIZARD_PROMPT}
                        </pre>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
                    <CopyButton text={WIZARD_PROMPT} label="Copy prompt" />
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/** Metrics PostHog AI suggests from the hypothesis and the project's events, each one added with one click. */
function SuggestMetricsDialog(): JSX.Element {
    const [added, setAdded] = useState<string[]>([])
    return (
        <Dialog>
            <DialogTrigger render={<Button variant="outline" size="sm" data-attr="checklist-suggest-metrics" />}>
                <IconSparkles />
                Suggest metrics
            </DialogTrigger>
            <DialogContent className="max-w-xl">
                <DialogHeader>
                    <DialogTitle>Suggested metrics</DialogTitle>
                    <DialogDescription>
                        PostHog AI read your hypothesis and the events your project sends. Add the ones that fit.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <ItemGroup className="flex flex-col gap-2">
                        {SUGGESTED_METRICS.map((metric) => {
                            const isAdded = added.includes(metric.key)
                            return (
                                <Item key={metric.key} size="sm" variant="outline">
                                    <ItemContent>
                                        <ItemTitle>
                                            {metric.name}
                                            <Badge>{metric.kind}</Badge>
                                        </ItemTitle>
                                        <ItemDescription>{metric.reason}</ItemDescription>
                                    </ItemContent>
                                    <ItemActions>
                                        <Button
                                            size="sm"
                                            variant={isAdded ? 'default' : 'outline'}
                                            onClick={() =>
                                                setAdded((current) =>
                                                    isAdded
                                                        ? current.filter((key) => key !== metric.key)
                                                        : [...current, metric.key]
                                                )
                                            }
                                        >
                                            {isAdded ? 'Added' : `Add as ${metric.role.toLowerCase()}`}
                                        </Button>
                                    </ItemActions>
                                </Item>
                            )
                        })}
                    </ItemGroup>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Done</DialogClose>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/** PostHog AI checks the whole setup before launch and lists what to fix. */
function SetupReviewDialog(): JSX.Element {
    return (
        <Dialog>
            <DialogTrigger render={<Button size="sm" data-attr="checklist-ai-review" />}>
                <IconSparkles />
                Review with PostHog AI
            </DialogTrigger>
            <DialogContent className="max-w-xl">
                <DialogHeader>
                    <DialogTitle>Setup review</DialogTitle>
                    <DialogDescription>
                        PostHog AI checked the flag, metrics, exposure and running time.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <ItemGroup className="flex flex-col gap-2">
                        {SETUP_REVIEW.map((finding) => (
                            <Item key={finding.title} size="sm" variant="outline">
                                <ItemMedia>
                                    {finding.tone === 'ok' ? (
                                        <IconCheckCircle className="text-success-foreground" />
                                    ) : (
                                        <IconWarning className="text-warning-foreground" />
                                    )}
                                </ItemMedia>
                                <ItemContent>
                                    <ItemTitle>{finding.title}</ItemTitle>
                                    <ItemDescription>{finding.detail}</ItemDescription>
                                </ItemContent>
                            </Item>
                        ))}
                    </ItemGroup>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

export function LaunchChecklist(): JSX.Element {
    const steps: {
        done: boolean
        title: string
        detail: string
        action: string | null
        ai: JSX.Element | null
    }[] = [
        {
            done: false,
            title: 'Add the feature flag to your code',
            detail: `Use the flag key ${EXPERIMENT.flagKey}.`,
            action: 'View code',
            ai: <WizardPromptDialog />,
        },
        {
            done: true,
            title: 'Add a primary metric',
            detail: '3 primary and 2 secondary metrics added.',
            action: null,
            ai: <SuggestMetricsDialog />,
        },
        { done: true, title: 'Review exposure criteria', detail: EXPOSURES.criteria, action: 'Edit', ai: null },
        {
            done: false,
            title: 'Set a running time target',
            detail: 'We estimate about 14 days at current traffic.',
            action: 'Set target',
            ai: null,
        },
    ]
    return (
        <Card size="sm">
            <CardContent className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="flex items-center gap-2">
                        <Heading size="sm" render={<h2 className="m-0" />}>
                            Before you launch
                        </Heading>
                        <Text size="xs" variant="muted" render={<span />}>
                            2 of 4 done
                        </Text>
                    </span>
                    <SetupReviewDialog />
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
                            {(step.action || step.ai) && (
                                <ItemActions className="flex-wrap justify-end">
                                    {step.ai}
                                    {step.action && (
                                        <Button variant="outline" size="sm">
                                            {step.action}
                                        </Button>
                                    )}
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
    'grid grid-cols-1 gap-4 @lg/main-content:grid-cols-2 @5xl/main-content:grid-cols-4 @7xl/main-content:grid-cols-1'
const WIDE_ONLY = 'hidden @7xl/main-content:block'

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
            className="-ml-1 cursor-grab touch-none text-muted-foreground opacity-0 transition-opacity group-hover/panel:opacity-100 focus-visible:opacity-100 active:cursor-grabbing"
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

/** Set by ContextPanels, so each panel card knows if it is collapsed and can toggle itself. */
const CollapsePanelContext = createContext<{ collapsed: boolean; toggle: () => void } | null>(null)

/**
 * A side card. The title toggles the body, so a collapsed card keeps one line: the title and its summary.
 * The summary is the one fact the card holds that the user most needs, so collapsing loses as little as possible.
 */
function PanelCard({
    title,
    summary,
    action,
    children,
}: {
    title: string
    summary?: React.ReactNode
    action?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    const collapse = useContext(CollapsePanelContext)
    const collapsed = collapse?.collapsed ?? false
    return (
        <Card size="sm" className="group/panel" data-collapsed={collapsed || undefined}>
            <CardHeader>
                <CardTitle className="min-w-0">
                    <span className="flex min-w-0 items-center gap-1">
                        <PanelDragHandle title={title} />
                        <button
                            type="button"
                            className="-mx-1 flex min-w-0 cursor-pointer items-center gap-1 rounded px-1 text-left hover:bg-fill-hover focus-visible:outline-2 focus-visible:outline-ring"
                            aria-expanded={!collapsed}
                            onClick={collapse?.toggle}
                            data-attr="panel-collapse"
                        >
                            <IconChevronDown
                                className={cn(
                                    'shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none',
                                    collapsed && '-rotate-90'
                                )}
                            />
                            <Text
                                size="xxs"
                                variant="muted"
                                weight="medium"
                                render={<span className="shrink-0 uppercase" />}
                            >
                                {title}
                            </Text>
                            {collapsed && summary && (
                                <Text size="xs" render={<span className="ml-1 truncate font-normal" />}>
                                    {summary}
                                </Text>
                            )}
                        </button>
                    </span>
                </CardTitle>
                <CardAction className="flex items-center gap-1">
                    <PanelHideButton title={title} />
                    {!collapsed && action}
                </CardAction>
            </CardHeader>
            {!collapsed && <CardContent className="flex flex-col gap-2">{children}</CardContent>}
        </Card>
    )
}

export function ExposuresChart(): JSX.Element {
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
    const edit = (
        <Button size="icon-xs" aria-label="Edit exposure criteria" tooltip="Edit exposure criteria">
            <IconPencil />
        </Button>
    )
    if (status === PROTOTYPE_STATUS.draft) {
        return (
            <PanelCard title="Exposures" summary="Counts show after launch" action={edit}>
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
        <PanelCard title="Exposures" summary={`${EXPOSURES.total}, split matches`} action={edit}>
            <Heading size="lg" render={<span />}>
                {EXPOSURES.total}
            </Heading>
            <div className="flex flex-col gap-1">
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
            <div className={WIDE_ONLY}>
                <ExposuresChart />
            </div>
        </PanelCard>
    )
}

function HealthPanel({ status }: { status: PrototypeStatus }): JSX.Element {
    return (
        <PanelCard
            title="Health"
            summary={
                status === PROTOTYPE_STATUS.running ? (
                    <span className="text-warning-foreground">{`${HEALTH_ISSUES.length} issues`}</span>
                ) : status === PROTOTYPE_STATUS.draft ? (
                    'After launch'
                ) : (
                    'No issues'
                )
            }
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
            summary={EXPERIMENT.hypothesis}
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
            summary={`${METHOD_LABEL[method]} · ${confidence}%${cuped ? ' · CUPED' : ''}`}
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
    collapsed,
    onToggleCollapsed,
}: {
    status: PrototypeStatus
    progress: RunProgress
    order: PanelKey[]
    onOrderChange: (order: PanelKey[]) => void
    hidden: PanelKey[]
    collapsed: PanelKey[]
    onToggleCollapsed: (key: PanelKey) => void
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
                        'items-start',
                        status === PROTOTYPE_STATUS.draft && '@5xl/main-content:grid-cols-3',
                        '@7xl/main-content:sticky @7xl/main-content:top-(--status-line-height) self-start'
                    )}
                >
                    {visible.map((key) => (
                        <SortablePanel key={key} id={key}>
                            <HidePanelContext.Provider value={() => onHide(key)}>
                                <CollapsePanelContext.Provider
                                    value={{ collapsed: collapsed.includes(key), toggle: () => onToggleCollapsed(key) }}
                                >
                                    {panels[key]}
                                </CollapsePanelContext.Provider>
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
const TYPE_HEADING_PX = 48

function MetricsTable({
    title,
    metrics,
    status,
    stickyTop,
    layout,
    chart,
    controls,
}: {
    title: string
    metrics: PrototypeMetric[]
    status: PrototypeStatus
    stickyTop: number
    layout: ResultLayout
    chart: ResultChart
    /** The result view switch, shown on the first section's heading only. */
    controls?: React.ReactNode
}): JSX.Element {
    const colors = useVariantColors()
    const rowChart = layout === RESULT_LAYOUT.perMetric
    const isDraft = status === PROTOTYPE_STATUS.draft
    const limit = axisLimit(metrics)
    const [headRef, headHeight] = useHeight<HTMLTableSectionElement>()
    const columnsTop = stickyTop + TYPE_HEADING_PX
    return (
        <section
            className="flex flex-col gap-2"
            style={{ '--quill-table-sticky-top': `${columnsTop}px` } as React.CSSProperties}
        >
            <div
                className="sticky z-15 -mx-1 flex items-center justify-between bg-background px-1"
                style={{ top: stickyTop, height: TYPE_HEADING_PX }}
            >
                <Heading size="sm" render={<h2 className="m-0" />}>
                    {title}
                </Heading>
                <div className="flex items-center gap-3">
                    {controls}
                    <Button size="sm">
                        <IconPlus />
                        {title === 'Primary metrics' ? 'Add primary metric' : 'Add secondary metric'}
                    </Button>
                </div>
            </div>
            {!isDraft && !rowChart && (
                <SectionResultChart chart={chart} title={title} metrics={metrics} colors={colors} limit={limit} />
            )}
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
                                            {chart === RESULT_CHART.candlestick
                                                ? 'Delta and interval'
                                                : chart === RESULT_CHART.matrix
                                                  ? 'Delta and chance to win'
                                                  : 'Delta over time'}
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
                                layout={layout}
                                chart={chart}
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
    layout,
    chart,
}: {
    metric: PrototypeMetric
    index: number
    colors: Record<string, string>
    limit: number
    isDraft: boolean
    stickyTop: number
    layout: ResultLayout
    chart: ResultChart
}): JSX.Element {
    const outcome = metricOutcome(metric)
    const rowChart = layout === RESULT_LAYOUT.perMetric
    return (
        <>
            <TableRow className="group/metric">
                {/* Each metric row sticks below the column names until the next metric row pushes it out. */}
                <TableCell
                    colSpan={5}
                    className="sticky z-10 border-b border-border bg-card pt-4"
                    style={{ top: stickyTop }}
                >
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <Text size="xs" weight="semibold" render={<span className="min-w-0 truncate" />}>
                            {index + 1}. {metric.name}
                        </Text>
                        <div className="ml-auto opacity-0 transition-opacity group-hover/metric:opacity-100 focus-within:opacity-100 motion-reduce:transition-none">
                            {!isDraft && <MetricActions />}
                        </div>
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
                                <Text size="xs" render={<span className="block" title={variant.detail} />}>
                                    {variant.value}
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
                                    <MetricRowChart
                                        chart={chart}
                                        metric={metric}
                                        height={metric.variants.length * ROW_HEIGHT - 12}
                                        trend={
                                            <PrototypeTrendChart
                                                trends={metricTrends(metric)}
                                                colors={colors}
                                                limit={limit}
                                                height={metric.variants.length * ROW_HEIGHT - 12}
                                                showValueAxis="yes"
                                            />
                                        }
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

function ResultsTab({
    status,
    progress,
    stickyTop,
    panelOrder,
    hiddenPanels,
    collapsedPanels,
    resultLayout,
    resultChart,
}: {
    status: PrototypeStatus
    progress: RunProgress
    stickyTop: number
    panelOrder: PanelKey[]
    hiddenPanels: PanelKey[]
    collapsedPanels: PanelKey[]
    resultLayout: ResultLayout
    resultChart: ResultChart
}): JSX.Element {
    const [layout, setLayout] = useState<ResultLayout>(resultLayout)
    const [chart, setChart] = useState<ResultChart>(resultChart)
    const [order, setOrder] = useState<PanelKey[]>(panelOrder)
    const [hidden, setHidden] = useState<PanelKey[]>(hiddenPanels)
    const [collapsed, setCollapsed] = useState<PanelKey[]>(collapsedPanels)
    const toggleCollapsed = (key: PanelKey): void =>
        setCollapsed((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]))
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
                'grid grid-cols-1 gap-x-10 gap-y-8 pt-6',
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
                        collapsed={collapsed}
                        onToggleCollapsed={toggleCollapsed}
                    />
                </div>
            )}
            <div className="flex min-w-0 flex-col gap-10 @7xl/main-content:col-start-1 @7xl/main-content:row-start-1">
                <MetricsTable
                    title="Primary metrics"
                    metrics={PRIMARY_METRICS}
                    status={status}
                    stickyTop={stickyTop}
                    layout={layout}
                    chart={chart}
                    controls={
                        <>
                            {allHidden && (
                                <HiddenCardsMenu
                                    hidden={hiddenAvailable}
                                    onShow={show}
                                    onShowAll={showAll}
                                    trigger={
                                        <Button size="sm" data-attr="panel-add-card">
                                            <IconPlus />
                                            Add card
                                        </Button>
                                    }
                                />
                            )}
                            {status !== PROTOTYPE_STATUS.draft && (
                                <CompactResultViewSwitch
                                    layout={layout}
                                    chart={chart}
                                    onLayoutChange={setLayout}
                                    onChartChange={setChart}
                                />
                            )}
                        </>
                    }
                />
                <MetricsTable
                    title="Secondary metrics"
                    metrics={SECONDARY_METRICS}
                    status={status}
                    stickyTop={stickyTop}
                    layout={layout}
                    chart={chart}
                />
            </div>
        </div>
    )
}

export function QuillPrototypeExperimentPageV20({
    status,
    shell,
    progress,
    panelOrder = DEFAULT_PANEL_ORDER,
    hiddenPanels = [],
    collapsedPanels = [],
    resultLayout = RESULT_LAYOUT.perMetric,
    resultChart = RESULT_CHART.trend,
}: {
    status: PrototypeStatus
    shell: ShellState
    progress: RunProgress
    panelOrder?: PanelKey[]
    hiddenPanels?: PanelKey[]
    collapsedPanels?: PanelKey[]
    resultLayout?: ResultLayout
    resultChart?: ResultChart
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
                        className="flex flex-1 flex-col gap-8 overflow-y-auto px-8 pb-16 *:shrink-0"
                        style={
                            {
                                '--quill-table-sticky-top': `${lineHeight}px`,
                                '--status-line-height': `${lineHeight + 24}px`,
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
                                    collapsedPanels={collapsedPanels}
                                    resultLayout={resultLayout}
                                    resultChart={resultChart}
                                />
                            </TabsContent>
                        </Tabs>
                    </div>
                </main>
            </div>
        </ToastProvider>
    )
}
