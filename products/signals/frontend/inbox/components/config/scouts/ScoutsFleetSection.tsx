import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconCompass, IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { captureScoutAction, captureScoutFleetViewed } from '../../../inboxAnalytics'
import type { ScoutChatType } from '../../../inboxAnalytics'
import { inboxSceneLogic } from '../../../inboxSceneLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { FleetSummary, SCOUT_RUNS_PER_SCOUT_LABEL } from '../../../utils/scoutRunsWindow'
import { agentSetupModalLogic } from '../../shell/agentSetupModalLogic'
import { FleetFindingsCallout } from './FleetFindingsCallout'
import { FleetMemoryCallout } from './FleetMemoryCallout'
import { ScoutCreateButton } from './ScoutCreateButton'
import { ScoutHelperSkillLinks } from './ScoutHelperSkillLinks'
import { ScoutRowCard } from './ScoutRowCard'
import { ScoutSuggestButton } from './ScoutSuggestButton'
import { ScoutTagsFilter } from './ScoutTagsFilter'

/**
 * Scout troop manager, hosted in the Scout troop setup modal (and the Agents settings tab). Both
 * hosts already title the section "Scout troop", so this always shows the full fleet: a stats
 * header (roster + run pulse) followed by every scout with inline config controls.
 * Cloud port of desktop's `ScoutsFleetSection`.
 */
export function ScoutsFleetSection(): JSX.Element {
    const { scoutConfigs, enabledCount, customScoutCount } = useValues(scoutFleetLogic)
    const { startRunsPolling, stopRunsPolling } = useActions(scoutFleetLogic)
    const { setScratchpadOpen, setFindingsOpen } = useActions(inboxSceneLogic)
    const { closeSetupModal } = useActions(agentSetupModalLogic)

    // Poll the runs window only while the fleet list is open — the always-mounted setup
    // widget reads configs only and shouldn't trigger the paginated runs requests.
    useEffect(() => {
        startRunsPolling()
        return () => stopRunsPolling()
    }, [startRunsPolling, stopRunsPolling])

    // Roster shape once per opening, the first time the fleet resolves. A failed load stays `null`
    // and reports nothing — an unreachable scout API isn't an empty troop.
    const fleetViewedFiredRef = useRef(false)
    useEffect(() => {
        if (scoutConfigs === null || fleetViewedFiredRef.current) {
            return
        }
        fleetViewedFiredRef.current = true
        captureScoutFleetViewed({
            scoutCount: scoutConfigs.length,
            enabledCount,
            customCount: customScoutCount,
            dryRunCount: scoutConfigs.filter((config) => !config.emit).length,
        })
    }, [scoutConfigs, enabledCount, customScoutCount])

    return (
        <div className="flex flex-col gap-3">
            <ScoutAlphaBanner />
            <FleetStatsHeader />
            <FleetFindingsCallout
                onOpen={() => {
                    captureScoutAction({ actionType: 'open_findings', surface: 'fleet_list' })
                    // This section can render inside the scout-troop setup modal; dismiss it so the
                    // findings view isn't left hidden behind the portal'd modal. No-op outside a modal.
                    closeSetupModal()
                    setFindingsOpen(true)
                }}
            />
            <FleetMemoryCallout
                onOpen={() => {
                    captureScoutAction({ actionType: 'open_memory', surface: 'fleet_list' })
                    // This section can render inside the scout-troop setup modal; dismiss it so the
                    // memory view isn't left hidden behind the portal'd modal. No-op outside a modal.
                    closeSetupModal()
                    setScratchpadOpen(true)
                }}
            />
            <ScoutsFleetList />
        </div>
    )
}

/**
 * Alpha/announcement banner for the scout troop, sourced from the `signals-scout` flag payload via
 * the metadata endpoint — so the copy (e.g. a run-limit notice) can change with no deploy. Renders
 * nothing when no message is set. Dismissal is remembered per-message, so a reworded notice resurfaces.
 */
function ScoutAlphaBanner(): JSX.Element | null {
    const { scoutBannerMessage, scoutMetadata, scoutMetadataLoading } = useValues(scoutFleetLogic)
    if (scoutMetadataLoading && scoutMetadata === null) {
        return <LemonSkeleton className="h-12 w-full rounded" />
    }
    if (!scoutBannerMessage) {
        return null
    }
    return (
        <LemonBanner type="info" dismissKey={`signals-scout-banner-${scoutBannerMessage}`}>
            {scoutBannerMessage}
        </LemonBanner>
    )
}

/** One-line fleet pulse: running, success rate, output on both emit channels + output rate. */
function summarize(summary: FleetSummary | null): string {
    if (!summary) {
        return 'None running now'
    }
    const parts = [summary.runningCount > 0 ? `${summary.runningCount} running now` : 'None running now']
    if (summary.successRate !== null) {
        parts.push(`${percentage(summary.successRate, 0)} success`)
    }
    // Output across both emit channels, zero parts dropped — a report-only fleet reads
    // "4 reports touched", not "0 signals emitted". The rate shares the channel-agnostic
    // definition of output (`emitRate`), so the count and the percentage always agree.
    const outputParts: string[] = []
    if (summary.emittedCount > 0) {
        outputParts.push(pluralize(summary.emittedCount, 'signal'))
    }
    if (summary.touchedReportCount > 0) {
        outputParts.push(`${pluralize(summary.touchedReportCount, 'report')} touched`)
    }
    if (outputParts.length === 0) {
        parts.push('no output yet')
    } else if (summary.emitRate !== null) {
        parts.push(`${outputParts.join(' · ')} (${percentage(summary.emitRate, 0)} of runs)`)
    } else {
        parts.push(outputParts.join(' · '))
    }
    return parts.join(' · ')
}

/**
 * Top-of-modal troop summary: roster (enabled / total + last dispatched) over the run pulse
 * (running / success / signals emitted across the window). Sits above the toggle row so the modal
 * leads with "what the troop is" before its controls.
 */
function FleetStatsHeader(): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading, enabledCount, lastRunAt, fleetSummary, scoutRunsLoadedOnce } =
        useValues(scoutFleetLogic)

    return (
        <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2 flex-wrap">
                {scoutConfigsLoading && scoutConfigs === null ? (
                    <LemonSkeleton className="h-4 w-40 rounded" />
                ) : (
                    <>
                        <span className="text-sm font-medium text-default">
                            {enabledCount} of {scoutConfigs?.length ?? enabledCount} scouts enabled
                        </span>
                        {lastRunAt ? (
                            <span className="text-xs text-secondary">
                                last dispatched <TZLabel time={lastRunAt} />
                            </span>
                        ) : null}
                    </>
                )}
            </div>
            {scoutRunsLoadedOnce ? (
                <span className="text-xs text-muted">
                    {summarize(fleetSummary)} · {SCOUT_RUNS_PER_SCOUT_LABEL} per scout
                </span>
            ) : (
                <LemonSkeleton className="h-3 w-72 rounded" />
            )}
        </div>
    )
}

function ScoutsFleetListSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <LemonSkeleton.Button />
                <LemonSkeleton.Button />
                <LemonSkeleton className="h-7 w-48 rounded" />
            </div>
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-16 w-full rounded" />
                <LemonSkeleton className="h-16 w-full rounded" />
                <LemonSkeleton className="h-16 w-full rounded" />
            </div>
        </div>
    )
}

function ScoutFleetError({ onRetry }: { onRetry: () => void }): JSX.Element {
    return (
        <div className="flex items-center gap-3 rounded border border-danger bg-danger-highlight px-4 py-3.5">
            <span className="flex-1 text-xs text-danger">
                Couldn't load the scout troop. The scout API may be unavailable or this project may not be enrolled yet.
            </span>
            <LemonButton type="secondary" size="small" status="danger" onClick={onRetry}>
                Retry
            </LemonButton>
        </div>
    )
}

function ScoutsFleetList(): JSX.Element {
    const {
        scoutConfigs,
        scoutConfigsLoading,
        visibleConfigs,
        rollups,
        hideDisabled,
        deletingScoutIds,
        updatingScoutIds,
        activeScoutTags,
        scoutTagOptions,
    } = useValues(scoutFleetLogic)
    const { setHideDisabled, setScoutTagFilter, updateScoutConfig, deleteScout, loadScoutConfigs } =
        useActions(scoutFleetLogic)

    if (scoutConfigsLoading && scoutConfigs === null) {
        return <ScoutsFleetListSkeleton />
    }

    // A failed request must not masquerade as an empty troop – a missing scope or
    // regional rollout gap would otherwise be indistinguishable from "no scouts yet".
    if (scoutConfigs === null) {
        return <ScoutFleetError onRetry={() => loadScoutConfigs()} />
    }

    if (scoutConfigs.length === 0) {
        return <ScoutsEmptyState />
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 flex-wrap">
                <ScoutCreateButton type="secondary" size="xsmall" onCreated={() => loadScoutConfigs()} />
                <ScoutSuggestButton type="secondary" size="xsmall" />
                <ScoutChatCta label="How is my scout troop performing?" chatType="fleet_overview" />
                <ScoutChatCta label="What signals were emitted recently?" chatType="recent_signals" />
                <span className="flex-1" />
                {scoutTagOptions.length > 0 ? (
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-muted">Tagged</span>
                        <ScoutTagsFilter
                            options={scoutTagOptions}
                            selected={activeScoutTags}
                            onToggle={(tag) =>
                                setScoutTagFilter(
                                    activeScoutTags.includes(tag)
                                        ? activeScoutTags.filter((candidate) => candidate !== tag)
                                        : [...activeScoutTags, tag]
                                )
                            }
                            onClear={() => setScoutTagFilter([])}
                        />
                    </div>
                ) : null}
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={() => {
                        captureScoutAction({
                            actionType: 'toggle_hide_disabled',
                            surface: 'fleet_list',
                            extra: { hide_disabled: !hideDisabled },
                        })
                        setHideDisabled(!hideDisabled)
                    }}
                >
                    {hideDisabled ? 'Show disabled' : 'Hide disabled'}
                </LemonButton>
            </div>

            {/* The enclosing modal owns the scroll, so the list stays flat here — a nested
                overflow container would create a scroll-area-within-a-scroll-area. */}
            <div className="flex flex-col gap-2">
                {visibleConfigs.length === 0 ? (
                    <span className="px-1 py-2 text-xs text-muted">No scouts match the current filters.</span>
                ) : (
                    visibleConfigs.map((config: SignalScoutConfig) => (
                        <ScoutRowCard
                            key={config.id}
                            config={config}
                            rollup={rollups.get(config.skill_name)}
                            onUpdate={updateScoutConfig}
                            onDelete={deleteScout}
                            deleting={deletingScoutIds.includes(config.id)}
                            updating={updatingScoutIds.includes(config.id)}
                        />
                    ))
                )}
            </div>

            <div className="flex flex-col gap-1">
                <span className="text-xs text-muted">
                    Run counts and emitted totals cover each scout’s {SCOUT_RUNS_PER_SCOUT_LABEL}, so scouts on
                    different schedules are comparable. New scouts are created as{' '}
                    <span className="font-mono text-[11px]">signals-scout-*</span> skills in your PostHog project.
                </span>
                <ScoutHelperSkillLinks />
            </div>
        </div>
    )
}

/**
 * Suggestion-chip CTA that fires an auto-mode cloud task asking a templated
 * question, then navigates to it – same one-click shape as the inbox
 * discuss / create-PR flows.
 */
function ScoutChatCta({
    label,
    chatType,
    icon,
}: {
    label: string
    chatType: ScoutChatType
    icon?: JSX.Element
}): JSX.Element {
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const { runningChatType, aiConsentDisabledReason } = useValues(scoutFleetLogic)
    const isRunning = runningChatType === chatType
    const anyRunning = runningChatType !== null
    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={icon ?? <IconSparkles />}
            loading={isRunning}
            disabledReason={anyRunning ? 'Starting a task…' : (aiConsentDisabledReason ?? undefined)}
            onClick={() => startScoutChatTask(chatType, label)}
        >
            {label}
        </LemonButton>
    )
}

function ScoutsEmptyState(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    return (
        <div className="flex flex-col items-start gap-2 rounded border border-primary bg-bg-light px-5 py-5">
            <div className="flex items-center gap-2">
                <IconCompass className="size-[18px] text-primary-3000" />
                <span className="font-medium text-sm text-default">No scouts on this project yet</span>
            </div>
            <p className="max-w-2xl text-xs text-secondary leading-snug mb-0">
                Create a scout to investigate a recurring signal or behavior on a schedule.
            </p>
            <div className="flex items-center gap-2 flex-wrap">
                <ScoutCreateButton onCreated={() => loadScoutConfigs()} />
                <ScoutSuggestButton />
            </div>
            <ScoutHelperSkillLinks />
        </div>
    )
}
