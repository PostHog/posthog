import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import {
    IconBell,
    IconChevronRight,
    IconCursorClick,
    IconDashboard,
    IconGraph,
    IconList,
    IconPlay,
    IconPulse,
    IconRefresh,
    IconTrending,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonCard,
    LemonCollapse,
    LemonDivider,
    LemonInput,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { maxContextLogic } from 'scenes/max/maxContextLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { PulseScanConfig } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

import { PulseFindingChart } from './PulseFindingChart'
import { pulseLogic } from './pulseLogic'
import { PulseDigestStatus, PulseDigestSummary, PulseFindingType, PulseSensitivity } from './pulseTypes'
import {
    SENSITIVITY_PRESETS,
    buildFindingInsightContext,
    buildFindingTimelineMarkers,
    buildMaxSeedPrompt,
    describeChange,
    suggestedNextStep,
} from './utils'

export const scene: SceneExport = {
    component: Pulse,
    logic: pulseLogic,
}

const FREQUENCY_OPTIONS: { value: 'weekly' | 'daily'; label: string }[] = [
    { value: 'weekly', label: 'Weekly' },
    { value: 'daily', label: 'Daily' },
]

const SENSITIVITY_OPTIONS: { value: PulseSensitivity; label: string }[] = [
    { value: 'conservative', label: 'Conservative' },
    { value: 'balanced', label: 'Balanced' },
    { value: 'sensitive', label: 'Sensitive' },
    { value: 'custom', label: 'Custom' },
]

const STATUS_TONES: Record<PulseDigestStatus, LemonTagType> = {
    delivered: 'success',
    failed: 'danger',
    generating: 'default',
    pending: 'default',
}

function statusTone(status: PulseDigestStatus): LemonTagType {
    return STATUS_TONES[status] ?? 'default'
}

// The digest synthesis is written as a "- " bullet list so it's skimmable; LemonMarkdown renders it (and
// still renders older paragraph-style summaries fine).
function DigestReadBanner({ summary, className }: { summary: string; className?: string }): JSX.Element {
    // type="ai" gives the premium AI-styled banner + icon; the body stays normal weight (LemonBanner
    // forces font-weight:500 on its content) while the "PostHog's read" header stays bold.
    return (
        <LemonBanner type="ai" className={className}>
            <div className="font-semibold mb-1">PostHog's read</div>
            <div className="font-normal">
                <LemonMarkdown>{summary}</LemonMarkdown>
            </div>
        </LemonBanner>
    )
}

// Skeleton mirroring the FindingCard layout (title / delta+sparkline / narrative) so loading reads as
// "cards coming" rather than generic bars.
function FindingCardSkeleton(): JSX.Element {
    return (
        <LemonCard className="border-l-4 border-muted">
            <div className="flex items-center justify-between mb-2">
                <LemonSkeleton className="h-5 w-48" />
                <LemonSkeleton className="h-6 w-28" />
            </div>
            <div className="flex items-end justify-between gap-4 mb-2">
                <LemonSkeleton className="h-8 w-32" />
                <LemonSkeleton className="h-10 w-28" />
            </div>
            <LemonSkeleton className="h-4 w-full mb-1" />
            <LemonSkeleton className="h-4 w-3/4" />
        </LemonCard>
    )
}

function FindingCard({
    finding,
    periodStart,
    periodEnd,
}: {
    finding: PulseFindingType
    periodStart: string
    periodEnd: string
}): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { addOrUpdateContextInsight } = useActions(maxContextLogic)
    const { dataProcessingAccepted, dataProcessingDismissed } = useValues(maxGlobalLogic)
    const change = describeChange(finding.change_pct)
    // Hand the AI the actual insight as structured context (so it can read_data on the real metric),
    // then open the panel and auto-send the seed. Falls back to prompt-only for event-sourced findings.
    const openExplore = (seed: string): void => {
        const insight = buildFindingInsightContext(finding)
        if (insight) {
            addOrUpdateContextInsight(insight)
        }
        openSidePanel(SidePanelTab.Max, `!${seed}`)
    }
    // Surface the specific guided lead as the button itself when we have one (e.g. "Dive into Chrome",
    // "Check the X experiment") so the suggested next step is proactive, not hidden behind a generic
    // label; fall back to a generic "Explore with AI" + explain-seed otherwise.
    const nextStep = suggestedNextStep(finding)
    const exploreSeed = nextStep?.seed ?? buildMaxSeedPrompt(finding)
    const exploreLabel = nextStep?.label ?? 'Explore with AI'

    // Border accent + delta tag + the chart line all share the change's tone (danger=drop, success=rise).
    const TrendIcon =
        change.direction === 'up' ? IconTrending : change.direction === 'down' ? IconTrendingDown : IconTrendingFlat
    // Prefer the daily series over the period (markers spread intra-day); fall back to the weekly series,
    // whose axis then runs one week per point back from the period end.
    const dailySeries = finding.evidence?.daily_series
    const useDaily = !!dailySeries && dailySeries.length > 1
    const chartSeries = useDaily ? dailySeries : (finding.evidence?.series ?? [])
    const axisStart =
        useDaily || chartSeries.length < 2
            ? periodStart
            : dayjs(periodEnd)
                  .subtract(chartSeries.length - 1, 'week')
                  .toISOString()
    const breakdown = finding.attribution_breakdown
    // The finding's referenced flag/experiment/annotation changes, placed on the same axis as the line.
    const timelineMarkers = buildFindingTimelineMarkers(finding, axisStart, periodEnd)
    const sessionIds = finding.evidence?.session_ids ?? []

    return (
        <LemonCard
            className={clsx(
                'border-l-4',
                change.tone === 'danger' && 'border-danger',
                change.tone === 'success' && 'border-success',
                change.tone === 'muted' && 'border-muted'
            )}
        >
            <div className="flex items-start gap-2 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                    <h3 className="text-base font-semibold mb-0 truncate">{finding.metric_label}</h3>
                </div>
                <div className="ml-auto flex items-center gap-1 shrink-0">
                    {finding.metric_descriptor?.url ? (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            to={finding.metric_descriptor.url as string}
                            targetBlank
                        >
                            View insight
                        </LemonButton>
                    ) : null}
                    <AIConsentPopoverWrapper onApprove={() => openExplore(exploreSeed)}>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            // While the consent popover is up, only its Approve should send the seed —
                            // a live onClick would fire pre-consent and then onApprove would send it again.
                            onClick={
                                dataProcessingAccepted || dataProcessingDismissed
                                    ? () => openExplore(exploreSeed)
                                    : undefined
                            }
                            sideIcon={null}
                        >
                            {exploreLabel}
                        </LemonButton>
                    </AIConsentPopoverWrapper>
                </div>
            </div>
            <div className="flex items-baseline gap-2 flex-wrap mb-2">
                <span className="text-2xl font-bold leading-none">
                    {humanFriendlyLargeNumber(finding.current_value)}
                </span>
                <LemonTag type={change.tone} icon={<TrendIcon />}>
                    {change.label}
                </LemonTag>
                <span className="text-muted-alt text-xs">
                    vs {humanFriendlyLargeNumber(finding.baseline_value)}/wk typical
                </span>
            </div>
            <p className="text-sm mb-0">{finding.narrative}</p>
            {breakdown?.value ? (
                <div className="flex items-center gap-1 text-muted-alt text-xs mt-2">
                    <span>Concentrated in</span>
                    {/* PropertyIcon.WithLabel's className styles only the icon wrapper, so render the icon and
                        the emphasized value separately — the icon is simply omitted for unmapped properties. */}
                    <PropertyIcon property={breakdown.property as string} value={String(breakdown.value)} />
                    <span className="font-medium text-default">{String(breakdown.value)}</span>
                </div>
            ) : null}
            {chartSeries.length > 1 || sessionIds.length ? <LemonDivider className="my-3" /> : null}
            {chartSeries.length > 1 ? (
                <PulseFindingChart
                    series={chartSeries}
                    markers={timelineMarkers}
                    axisStart={axisStart}
                    axisEnd={periodEnd}
                    tone={change.tone}
                />
            ) : null}
            {sessionIds.length ? (
                <div className="flex items-center flex-wrap gap-2 mt-2 text-xs">
                    <span className="text-muted-alt">Sessions:</span>
                    {sessionIds.map((sessionId, index) => (
                        <LemonButton
                            key={sessionId}
                            type="secondary"
                            size="xsmall"
                            icon={<IconPlay />}
                            to={urls.replaySingle(sessionId)}
                            targetBlank
                        >
                            Session {index + 1}
                        </LemonButton>
                    ))}
                </div>
            ) : null}
        </LemonCard>
    )
}

function SubscriptionPanel(): JSX.Element {
    const { subscriptionDraft, subscriptionLoading } = useValues(pulseLogic)
    const { updateSubscriptionLocal, saveSubscription } = useActions(pulseLogic)

    if (!subscriptionDraft) {
        return <LemonSkeleton className="h-40 w-full mb-6" />
    }

    const setSensitivity = (sensitivity: PulseSensitivity): void => {
        if (sensitivity === 'custom') {
            updateSubscriptionLocal({ sensitivity })
            return
        }
        updateSubscriptionLocal({ sensitivity, ...SENSITIVITY_PRESETS[sensitivity] })
    }

    return (
        <LemonCard className="mb-6">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-base font-semibold mb-0">Pulse settings</h3>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => saveSubscription()}
                    loading={subscriptionLoading}
                    disabledReason={subscriptionLoading ? 'Saving…' : undefined}
                >
                    Save settings
                </LemonButton>
            </div>
            <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                    <span>Enable Pulse</span>
                    <LemonSwitch
                        checked={subscriptionDraft.enabled}
                        onChange={(checked) => updateSubscriptionLocal({ enabled: checked })}
                    />
                </div>
                <div className="flex items-center justify-between">
                    <span>Frequency</span>
                    <LemonSelect
                        value={subscriptionDraft.frequency}
                        onChange={(v) => v && updateSubscriptionLocal({ frequency: v })}
                        options={FREQUENCY_OPTIONS}
                    />
                </div>
                <div className="flex items-center justify-between">
                    <Tooltip title="Controls the always-on metric scan. Anomalies surfaced by the AI scout aren't filtered by these thresholds.">
                        <span>Sensitivity</span>
                    </Tooltip>
                    <LemonSegmentedButton
                        value={subscriptionDraft.sensitivity}
                        onChange={(v) => setSensitivity(v)}
                        options={SENSITIVITY_OPTIONS}
                        size="small"
                    />
                </div>
                <LemonCollapse
                    panels={[
                        {
                            key: 'advanced',
                            header: 'Advanced',
                            content: (
                                <div className="flex flex-col gap-3">
                                    <div className="flex items-center justify-between">
                                        <span>Minimum change %</span>
                                        <LemonInput
                                            type="number"
                                            step={0.05}
                                            value={subscriptionDraft.min_change_pct}
                                            onChange={(v) =>
                                                updateSubscriptionLocal({
                                                    min_change_pct: v ?? 0,
                                                    sensitivity: 'custom',
                                                })
                                            }
                                        />
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span>Baseline weeks</span>
                                        <LemonInput
                                            type="number"
                                            value={subscriptionDraft.baseline_weeks}
                                            onChange={(v) => updateSubscriptionLocal({ baseline_weeks: v ?? 4 })}
                                        />
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span>Maximum findings</span>
                                        <LemonInput
                                            type="number"
                                            value={subscriptionDraft.max_findings}
                                            onChange={(v) => updateSubscriptionLocal({ max_findings: v ?? 5 })}
                                        />
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span>Robust z threshold</span>
                                        <LemonInput
                                            type="number"
                                            step={0.5}
                                            value={subscriptionDraft.robust_z_threshold}
                                            onChange={(v) =>
                                                updateSubscriptionLocal({
                                                    robust_z_threshold: v ?? 3.5,
                                                    sensitivity: 'custom',
                                                })
                                            }
                                        />
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonCard>
    )
}

// Icon + readable label per watched-metric source, so a glance tells dashboard vs insight vs event.
const WATCHED_META: Record<string, { icon: JSX.Element; label: string }> = {
    dashboard_tile: { icon: <IconDashboard />, label: 'Dashboard tile' },
    recent_insight: { icon: <IconGraph />, label: 'Insight' },
    saved_insight: { icon: <IconGraph />, label: 'Insight' },
    top_event: { icon: <IconCursorClick />, label: 'Event' },
}

function WatchedPanel(): JSX.Element | null {
    const { watchedCandidates, watchedCandidatesLoading } = useValues(pulseLogic)

    if (watchedCandidatesLoading) {
        return <LemonSkeleton className="h-24 w-full mb-6" />
    }
    if (!watchedCandidates.length) {
        return null
    }

    return (
        <LemonCard className="mb-6">
            <div className="flex items-center gap-2 mb-2">
                <h3 className="text-base font-semibold mb-0">What PostHog is watching</h3>
                <LemonTag type="warning">Staff debug</LemonTag>
            </div>
            <p className="text-muted-alt text-sm mb-3">
                Internal: the metric set scanned each cycle. Hidden from non-staff while we tune it.
            </p>
            <div className="flex flex-wrap gap-2">
                {watchedCandidates.map((c, i) => {
                    const meta = WATCHED_META[c.source] ?? { icon: <IconList />, label: 'Metric' }
                    return (
                        <Tooltip key={c.source_id ?? `${c.source}-${i}`} title={meta.label}>
                            <LemonTag type="muted" icon={meta.icon}>
                                {c.label}
                            </LemonTag>
                        </Tooltip>
                    )
                })}
            </div>
        </LemonCard>
    )
}

// Knob definitions for the staff scan-tuning panel — kept module-level so they aren't rebuilt each render.
type ScanKnob = { key: keyof PulseScanConfig; label: string; step?: number; hint?: string }
const SELECTION_KNOBS: ScanKnob[] = [
    { key: 'max_candidates', label: 'Max candidates' },
    { key: 'recent_days', label: 'Recent window (days)' },
    { key: 'min_viewers_for_recent_insight', label: 'Min viewers (recent insights)' },
    { key: 'dashboard_tile_limit', label: 'Dashboard tiles', hint: '0 = off' },
    { key: 'recent_insight_limit', label: 'Recently-viewed insights', hint: '0 = off' },
    { key: 'saved_insight_limit', label: 'Saved insights', hint: '0 = off' },
    { key: 'top_event_limit', label: 'Top events', hint: '0 = off' },
]
const DETECTION_KNOBS: ScanKnob[] = [
    { key: 'min_baseline_value', label: 'Volume floor (min baseline)', step: 1 },
    { key: 'min_change_pct', label: 'Min change %', step: 0.05 },
    { key: 'robust_z_threshold', label: 'Robust z threshold', step: 0.5 },
    { key: 'baseline_weeks', label: 'Baseline weeks' },
    { key: 'max_findings', label: 'Max findings' },
]

// Staff-only knobs for one-off, no-deploy tuning of what Pulse considers interesting. The draft is local
// (persisted to localStorage); "Run scan with these settings" sends it as a per-run override — nothing is
// saved to the team. A plain "Run scan now" (no config) still uses the team's saved subscription settings.
function ScanTuningPanel(): JSX.Element {
    const { scanConfigDraft, scanTriggerLoading } = useValues(pulseLogic)
    const { updateScanConfigLocal, resetScanConfig, triggerScan } = useActions(pulseLogic)

    const renderKnob = (knob: ScanKnob): JSX.Element => (
        <div key={knob.key} className="flex items-center justify-between gap-2">
            <span className="text-sm">
                {knob.label}
                {knob.hint ? <span className="text-muted-alt ml-1">({knob.hint})</span> : null}
            </span>
            <LemonInput
                type="number"
                size="small"
                className="w-24"
                step={knob.step}
                value={scanConfigDraft[knob.key]}
                onChange={(v) =>
                    // LemonInput type="number" emits NaN (not undefined) for an empty field, and NaN ?? x
                    // doesn't catch it — so guard on finiteness to keep NaN out of the draft and the request.
                    Number.isFinite(v) && updateScanConfigLocal({ [knob.key]: v as number } as Partial<PulseScanConfig>)
                }
            />
        </div>
    )

    return (
        <LemonCard className="mb-6">
            <div className="flex items-center gap-2 mb-2">
                <h3 className="text-base font-semibold mb-0">Scan tuning</h3>
                <LemonTag type="warning">Staff debug</LemonTag>
            </div>
            <p className="text-muted-alt text-sm mb-3">
                Internal: override the heuristics for a single one-off scan to calibrate what's interesting — nothing
                here is saved to the team.
            </p>
            <LemonCollapse
                panels={[
                    {
                        key: 'knobs',
                        header: 'Knobs',
                        content: (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
                                <div className="flex flex-col gap-3">
                                    <h4 className="text-xs uppercase font-semibold text-muted mb-0">Selection</h4>
                                    {SELECTION_KNOBS.map(renderKnob)}
                                </div>
                                <div className="flex flex-col gap-3">
                                    <h4 className="text-xs uppercase font-semibold text-muted mb-0">Detection</h4>
                                    {DETECTION_KNOBS.map(renderKnob)}
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
            <div className="flex items-center gap-2 mt-3">
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPulse />}
                    onClick={() => triggerScan(scanConfigDraft)}
                    loading={scanTriggerLoading}
                    disabledReason={scanTriggerLoading ? 'Scan starting…' : undefined}
                >
                    Run scan with these settings
                </LemonButton>
                <LemonButton type="secondary" size="small" onClick={() => resetScanConfig()}>
                    Reset to defaults
                </LemonButton>
            </div>
        </LemonCard>
    )
}

function DigestRow({ digest }: { digest: PulseDigestSummary }): JSX.Element {
    const { expandedDigestId, expandedDigest, expandedDigestLoading } = useValues(pulseLogic)
    const { setExpandedDigestId, getDigest } = useActions(pulseLogic)
    const isExpanded = expandedDigestId === digest.id

    const onToggle = (): void => {
        if (isExpanded) {
            setExpandedDigestId(null)
            return
        }
        setExpandedDigestId(digest.id)
        if (expandedDigest?.id !== digest.id) {
            getDigest(digest.id)
        }
    }

    return (
        <li className="border rounded bg-surface-primary">
            <button
                type="button"
                className="w-full flex items-center justify-between p-3 cursor-pointer bg-transparent border-none text-left"
                onClick={onToggle}
                aria-expanded={isExpanded}
            >
                <span className="flex items-center gap-2 font-medium">
                    <IconChevronRight
                        className={isExpanded ? 'rotate-90 transition-transform' : 'transition-transform'}
                    />
                    <TZLabel time={digest.created_at} />
                    <LemonTag type={statusTone(digest.status)}>{digest.status}</LemonTag>
                </span>
                <span className="text-muted-alt text-sm">
                    {digest.finding_count} finding{digest.finding_count === 1 ? '' : 's'}
                </span>
            </button>
            {isExpanded && (
                <div className="p-3 pt-0 space-y-3">
                    {digest.status === 'failed' ? (
                        <LemonBanner type="error">
                            <span className="font-semibold">Scan failed: </span>
                            {digest.error?.message ?? 'Unknown error'}
                        </LemonBanner>
                    ) : null}
                    {expandedDigestLoading || expandedDigest?.id !== digest.id ? (
                        <LemonSkeleton className="h-24 w-full" />
                    ) : expandedDigest.findings.length === 0 ? (
                        <p className="text-muted mb-0">No findings in this digest.</p>
                    ) : (
                        <>
                            {expandedDigest.summary ? <DigestReadBanner summary={expandedDigest.summary} /> : null}
                            {expandedDigest.findings.map((finding) => (
                                <FindingCard
                                    key={finding.id}
                                    finding={finding}
                                    periodStart={expandedDigest.period_start}
                                    periodEnd={expandedDigest.period_end}
                                />
                            ))}
                        </>
                    )}
                </div>
            )}
        </li>
    )
}

export function Pulse(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        digests,
        digestsLoading,
        findingsLoading,
        shouldShowEmptyState,
        latestDigest,
        findingsForLatest,
        digestsError,
        findingsError,
        subscriptionError,
        watchedError,
        scanTriggerLoading,
        isScanInProgress,
        digestsNext,
        loadingMore,
    } = useValues(pulseLogic)
    const { loadDigests, loadMoreDigests, loadFindings, loadSubscription, loadWatched, triggerScan, setUpPulseAlerts } =
        useActions(pulseLogic)
    const { user } = useValues(userLogic)

    const flagEnabled = !!featureFlags[FEATURE_FLAGS.MAX_PULSE]

    useEffect(() => {
        if (!flagEnabled) {
            return
        }
        loadDigests()
        loadFindings()
        loadSubscription()
        if (user?.is_staff) {
            loadWatched() // staff-only debug panel; don't fetch the watched set for non-staff
        }
    }, [flagEnabled, user?.is_staff, loadDigests, loadFindings, loadSubscription, loadWatched])

    if (!flagEnabled) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Pulse"
                    description="PostHog scans your metrics and surfaces changes worth investigating."
                    resourceType={{ type: 'project', forceIcon: <IconPulse /> }}
                />
                <ProductIntroduction
                    productName="Pulse"
                    thingName="finding"
                    description="PostHog scans your metrics each cycle and surfaces notable changes worth investigating. Pulse is rolling out gradually."
                    isEmpty
                    docsURL="https://posthog.com/docs"
                />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Pulse"
                description="PostHog scans your metrics and surfaces changes worth investigating."
                resourceType={{ type: 'project', forceIcon: <IconPulse /> }}
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconBell />}
                            onClick={() => setUpPulseAlerts()}
                            tooltip="Get notified in Slack when Pulse surfaces a finding (routes the pulse_finding_surfaced event to a destination)"
                        >
                            Set up alerts
                        </LemonButton>
                        {user?.is_staff && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPulse />}
                                onClick={() => triggerScan()}
                                loading={scanTriggerLoading}
                                tooltip="Staff only: run a Pulse scan for this project now"
                            >
                                Run scan now
                            </LemonButton>
                        )}
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            onClick={() => {
                                loadDigests()
                                loadFindings()
                            }}
                            loading={digestsLoading || findingsLoading}
                        >
                            Refresh
                        </LemonButton>
                    </>
                }
            />

            <SubscriptionPanel />
            {/* The watched-metric set and the scan-tuning knobs are internal "magic sauce" we'll keep tuning —
                staff-only debug while we calibrate on production data. */}
            {user?.is_staff && <WatchedPanel />}
            {user?.is_staff && <ScanTuningPanel />}

            {digestsError && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadDigests() }} className="mb-4">
                    Failed to load Pulse digests.
                </LemonBanner>
            )}
            {findingsError && (
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => loadFindings() }}
                    className="mb-4"
                >
                    Failed to load findings.
                </LemonBanner>
            )}
            {subscriptionError && (
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => loadSubscription() }}
                    className="mb-4"
                >
                    Failed to load Pulse settings.
                </LemonBanner>
            )}
            {watchedError && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadWatched() }} className="mb-4">
                    Failed to load the watched metrics.
                </LemonBanner>
            )}

            {isScanInProgress && (
                <LemonBanner type="info" className="mb-4">
                    <span className="flex items-center gap-2">
                        <Spinner />
                        Scan in progress — findings will appear here as soon as it finishes…
                    </span>
                </LemonBanner>
            )}

            {digestsLoading && digests.length === 0 ? (
                <div className="space-y-4">
                    <LemonSkeleton className="h-8 w-48" />
                    <FindingCardSkeleton />
                    <FindingCardSkeleton />
                </div>
            ) : (
                <>
                    <ProductIntroduction
                        productName="Pulse"
                        thingName="finding"
                        description="Once Pulse runs its first scan, findings will appear here."
                        isEmpty={shouldShowEmptyState}
                        docsURL="https://posthog.com/docs"
                    />
                    {!shouldShowEmptyState && (
                        <div className="space-y-6">
                            {latestDigest && (
                                <div>
                                    <div className="flex items-center gap-2 mb-3">
                                        <h2 className="text-lg font-semibold mb-0">Latest digest</h2>
                                        <LemonTag type={statusTone(latestDigest.status)}>
                                            {latestDigest.status}
                                        </LemonTag>
                                        <span className="text-muted-alt text-xs">
                                            <TZLabel time={latestDigest.created_at} />
                                        </span>
                                    </div>
                                    {latestDigest.status === 'failed' ? (
                                        <LemonBanner type="error" className="mb-3">
                                            <span className="font-semibold">Scan failed: </span>
                                            {latestDigest.error?.message ?? 'Unknown error'}
                                        </LemonBanner>
                                    ) : null}
                                    {latestDigest.summary ? (
                                        <DigestReadBanner summary={latestDigest.summary} className="mb-3" />
                                    ) : null}
                                    {findingsForLatest.length === 0 ? (
                                        <p className="text-muted">No findings in the latest digest.</p>
                                    ) : (
                                        <div className="grid grid-cols-1 gap-4">
                                            {findingsForLatest.map((finding) => (
                                                <FindingCard
                                                    key={finding.id}
                                                    finding={finding}
                                                    periodStart={latestDigest.period_start}
                                                    periodEnd={latestDigest.period_end}
                                                />
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}

                            {digests.length > 1 && (
                                <div>
                                    <h2 className="text-lg font-semibold mb-3">Previous digests</h2>
                                    <ul className="space-y-2">
                                        {digests.slice(1).map((digest) => (
                                            <DigestRow key={digest.id} digest={digest} />
                                        ))}
                                    </ul>
                                    {digestsNext && (
                                        <div className="flex justify-center mt-3">
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                onClick={() => loadMoreDigests()}
                                                loading={loadingMore}
                                                disabledReason={loadingMore ? 'Loading…' : undefined}
                                            >
                                                Load more previous digests
                                            </LemonButton>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}
        </SceneContent>
    )
}

export default Pulse
