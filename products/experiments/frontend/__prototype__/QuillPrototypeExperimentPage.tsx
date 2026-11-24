/** Scratch prototype v3: the v2 page rebuilt on Quill for the today-rail-nav shell. Not committed. */
import { useMemo } from 'react'

import {
    IconCheckCircle,
    IconCircleDashed,
    IconCopy,
    IconEllipsis,
    IconFlag,
    IconFlask,
    IconPencil,
    IconWarning,
} from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
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
import { Sparkline } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

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

export const DETAILS_STATE = { open: 'open', closed: 'closed' } as const
export type DetailsState = (typeof DETAILS_STATE)[keyof typeof DETAILS_STATE]

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
function FakeShell(): JSX.Element {
    return (
        <>
            <div className="flex w-15 shrink-0 flex-col items-center gap-3 bg-chrome py-3">
                {Array.from({ length: 5 }, (_, index) => (
                    <div key={index} className="size-8 rounded-md bg-fill-hover" />
                ))}
            </div>
            <div className="flex w-72 shrink-0 flex-col gap-2 border-r border-border bg-chrome p-3">
                <div className="h-10.5 -mx-3 -mt-3 mb-1 border-b border-border" />
                {Array.from({ length: 12 }, (_, index) => (
                    <div key={index} className="h-5 rounded-sm bg-fill-hover" />
                ))}
            </div>
        </>
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

function MetaLine({ status }: { status: PrototypeStatus }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <StatusBadge status={status} />
            {status === PROTOTYPE_STATUS.running && (
                <Badge variant="warning">
                    <IconWarning />
                    {HEALTH_ISSUES.length} issues
                </Badge>
            )}
            {status === PROTOTYPE_STATUS.running && (
                <div className="flex items-center gap-2">
                    <Progress value={64} variant="success" className="w-16" />
                    <Text size="xs" render={<span />}>
                        Day 9 of ~14
                    </Text>
                </div>
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
            {status === PROTOTYPE_STATUS.running && (
                <Text size="xs" variant="muted" render={<span className="ml-auto" />}>
                    Refreshed 9 minutes ago ·{' '}
                    <Button variant="link" size="inline">
                        Refresh
                    </Button>
                </Text>
            )}
        </div>
    )
}

function Verdict({ status }: { status: PrototypeStatus }): JSX.Element {
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
    return (
        <Card size="sm">
            <CardContent className="flex items-center gap-4">
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <Text size="xxs" variant="muted" weight="medium" render={<span className="uppercase" />}>
                        Checkout completed · primary metric 1 of 3
                    </Text>
                    <Heading size="base" render={<h2 className="m-0" />}>
                        one-page leads with <span className="text-success-foreground">+8.4%</span> completed checkouts
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        99% chance to win · 95% credible interval +3.1% to +13.9% · 1 of 3 primary metrics significant
                    </Text>
                </div>
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-48" />}>
                    About 5 days left to reach the target of 18,000 exposures.
                </Text>
            </CardContent>
        </Card>
    )
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
                <ItemGroup className="grid grid-cols-2 gap-2">
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

function ContextRow({ status }: { status: PrototypeStatus }): JSX.Element {
    const isDraft = status === PROTOTYPE_STATUS.draft
    const exposuresTotal = useMemo(
        () => EXPOSURES.days.map((_, index) => VARIANTS.reduce((sum, key) => sum + EXPOSURES.daily[key][index], 0)),
        []
    )
    return (
        <Card size="sm">
            <CardContent className="grid grid-cols-3 gap-4">
                <div className="flex flex-col gap-1">
                    <Text size="xxs" variant="muted" weight="medium" render={<span className="uppercase" />}>
                        Exposures
                    </Text>
                    {isDraft ? (
                        <Text size="xs" render={<p className="m-0" />}>
                            {EXPOSURES.criteria}. Counts show after launch.
                        </Text>
                    ) : (
                        <>
                            <div className="flex items-center gap-3">
                                <Heading size="lg" render={<span />}>
                                    {EXPOSURES.total}
                                </Heading>
                                <div className="w-24">
                                    <Sparkline data={exposuresTotal} height={24} />
                                </div>
                            </div>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                33.3% · 33.5% · 33.2% · split matches the target
                            </Text>
                        </>
                    )}
                </div>
                <div className="flex flex-col gap-1">
                    <Text size="xxs" variant="muted" weight="medium" render={<span className="uppercase" />}>
                        Health
                    </Text>
                    {status === PROTOTYPE_STATUS.running ? (
                        <>
                            <Text size="xs" weight="medium" render={<p className="m-0" />}>
                                {HEALTH_ISSUES[0].title}
                            </Text>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                and 1 more ·{' '}
                                <Button variant="link" size="inline">
                                    View all
                                </Button>
                            </Text>
                        </>
                    ) : (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {isDraft ? 'Checks run after launch.' : 'No issues found.'}
                        </Text>
                    )}
                </div>
                <div className="flex flex-col gap-1">
                    <Text size="xxs" variant="muted" weight="medium" render={<span className="uppercase" />}>
                        Setup
                    </Text>
                    <Text size="xs" render={<p className="m-0" />}>
                        {EXPERIMENT.statsMethod} · {EXPERIMENT.confidence} · 3 variants, equal split
                    </Text>
                    <Text size="xs" variant="muted" render={<p className="m-0 flex items-center gap-1" />}>
                        <IconFlag />
                        <span className="font-mono">{EXPERIMENT.flagKey}</span>
                        <IconCopy />
                    </Text>
                </div>
            </CardContent>
        </Card>
    )
}

function DetailsSection({ detailsState }: { detailsState: DetailsState }): JSX.Element {
    const colors = useVariantColors()
    const series = useMemo(
        () => VARIANTS.map((key) => ({ key, label: key, data: EXPOSURES.daily[key], color: colors[key] })),
        [colors]
    )
    return (
        <Collapsible defaultOpen={detailsState === DETAILS_STATE.open}>
            <CollapsibleTrigger>Hypothesis and exposures</CollapsibleTrigger>
            <CollapsibleContent>
                <div className="grid grid-cols-2 gap-4 pt-2">
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-1">
                            <Heading size="sm" render={<h3 className="m-0" />}>
                                Hypothesis
                            </Heading>
                            <Button size="icon-xs" aria-label="Edit hypothesis" tooltip="Edit hypothesis">
                                <IconPencil />
                            </Button>
                        </div>
                        <Text size="xs" render={<p className="m-0" />}>
                            {EXPERIMENT.hypothesis}
                        </Text>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Created by {EXPERIMENT.owner} · started {EXPERIMENT.startDate}
                        </Text>
                    </div>
                    <div className="flex flex-col gap-2">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Exposures per day
                        </Heading>
                        <Sparkline series={series} height={96} />
                    </div>
                </div>
            </CollapsibleContent>
        </Collapsible>
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
            <Card size="sm" flush>
                <Table size="sm" fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-44">Metric</TableHead>
                            <TableHead>Variant</TableHead>
                            <TableHead align="right">Value</TableHead>
                            <TableHead align="right">Delta</TableHead>
                            <TableHead align="right">Chance to win</TableHead>
                            <TableHead expand>
                                {!isDraft && (
                                    <span className="flex justify-between gap-2">
                                        <span>Delta over time</span>
                                        <span className="font-normal">
                                            Nov 3 to Nov 16 · ±{Math.round(limit * 100)}%
                                        </span>
                                    </span>
                                )}
                            </TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {metrics.map((metric, metricIndex) =>
                            metric.variants.map((variant, variantIndex) => {
                                const significant =
                                    variant.interval !== null && (variant.interval[0] > 0 || variant.interval[1] < 0)
                                return (
                                    <TableRow key={`${metric.name}-${variant.key}`} style={{ height: ROW_HEIGHT }}>
                                        {variantIndex === 0 && (
                                            <TableCell
                                                rowSpan={metric.variants.length}
                                                valign="top"
                                                className="w-44 border-r border-border"
                                            >
                                                <div className="flex min-w-36 flex-col items-start gap-1 pt-1">
                                                    <Text size="xs" weight="medium" render={<span />}>
                                                        {metricIndex + 1}. {metric.name}
                                                    </Text>
                                                    <Badge>{metric.kind}</Badge>
                                                </div>
                                            </TableCell>
                                        )}
                                        <TableCell>
                                            <span className="flex items-center gap-2 whitespace-nowrap">
                                                <VariantDot color={colors[variant.key]} />
                                                <span className="font-mono text-xs">{variant.key}</span>
                                            </span>
                                        </TableCell>
                                        {isDraft ? (
                                            variantIndex === 0 ? (
                                                <TableCell colSpan={4} rowSpan={metric.variants.length} align="center">
                                                    <Text size="xs" variant="muted" render={<span />}>
                                                        Results show after launch
                                                    </Text>
                                                </TableCell>
                                            ) : null
                                        ) : (
                                            <>
                                                <TableCell align="right" className="whitespace-nowrap tabular-nums">
                                                    <Text size="xs" render={<span className="block" />}>
                                                        {variant.value}
                                                    </Text>
                                                    <Text
                                                        size="xxs"
                                                        variant="muted"
                                                        render={<span className="block" />}
                                                    >
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
                                                        {variant.delta === null
                                                            ? 'Baseline'
                                                            : formatDelta(variant.delta)}
                                                    </Text>
                                                </TableCell>
                                                <TableCell align="right" className="tabular-nums">
                                                    <Text size="xs" render={<span />}>
                                                        {variant.chanceToWin === null
                                                            ? ''
                                                            : formatChance(variant.chanceToWin)}
                                                    </Text>
                                                </TableCell>
                                                {variantIndex === 0 && (
                                                    <TableCell
                                                        rowSpan={metric.variants.length}
                                                        className="border-l border-border"
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
                                            </>
                                        )}
                                    </TableRow>
                                )
                            })
                        )}
                    </TableBody>
                </Table>
            </Card>
        </section>
    )
}

function ResultsTab({ status }: { status: PrototypeStatus }): JSX.Element {
    return (
        <div className="flex flex-col gap-4 pt-3">
            <MetricsTable title="Primary metrics" metrics={PRIMARY_METRICS} status={status} />
            <MetricsTable title="Secondary metrics" metrics={SECONDARY_METRICS} status={status} />
        </div>
    )
}

export function QuillPrototypeExperimentPage({
    status,
    detailsState,
}: {
    status: PrototypeStatus
    detailsState: DetailsState
}): JSX.Element {
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
            <FakeShell />
            <main className="flex min-w-0 flex-1 flex-col">
                <QuillSceneHeader
                    icon={<IconFlask />}
                    title={<SceneTitle />}
                    actions={<SceneActions status={status} />}
                />
                <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
                    <MetaLine status={status} />
                    <Verdict status={status} />
                    <ContextRow status={status} />
                    <DetailsSection detailsState={detailsState} />
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
