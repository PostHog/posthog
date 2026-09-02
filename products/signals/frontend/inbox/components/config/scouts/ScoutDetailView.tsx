import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { captureScoutDetailViewed } from '../../../inboxAnalytics'
import { inboxSceneLogic } from '../../../inboxSceneLogic'
import { scoutDetailLogic } from '../../../logics/scoutDetailLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutNotesLogic } from '../../../logics/scoutNotesLogic'
import { entriesForSkill, scratchpadLogic } from '../../../logics/scratchpadLogic'
import { SCOUT_NO_RECENT_RUNS, SCOUT_RUNS_PER_SCOUT_LABEL } from '../../../utils/scoutRunsWindow'
import { ScoutDetailHeader, ScoutAttentionBanner } from './ScoutDetailHeader'
import { ScoutEmissionCard } from './ScoutEmissionCard'
import { ScoutLearnedPanel } from './ScoutLearnedPanel'
import { ScoutNotesPanel } from './ScoutNotesPanel'
import { ScoutReportCard } from './ScoutReportCard'
import { ScoutRunHistorySection } from './ScoutRunHistorySection'

/**
 * One scout's page, at `/inbox/scouts/:skillName`. In order of what a reader needs: anything the
 * scheduler wants decided, then what the scout produced, and down the side what it has worked out
 * for itself and what the team has told it. Configuration lives behind the header's settings modal —
 * this page is for reading the scout, not adjusting it.
 */
export function ScoutDetailView({ skillName }: { skillName: string }): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading, rollups } = useValues(scoutFleetLogic)
    const { startRunsPolling, stopRunsPolling, loadScoutConfigs } = useActions(scoutFleetLogic)
    const { entries } = useValues(scratchpadLogic)
    const { scoutNotes } = useValues(scoutNotesLogic({ skillName }))

    // Deep-linking straight to a scout (or a narrow viewport where the roster isn't mounted)
    // means nobody else is polling the runs window, so the header + rollup would read empty
    // defaults. Drive the same start/stop lifecycle the roster uses.
    useEffect(() => {
        startRunsPolling()
        return () => stopRunsPolling()
    }, [startRunsPolling, stopRunsPolling])

    const config = scoutConfigs?.find((c) => c.skill_name === skillName) ?? null
    const rollup = rollups.get(skillName)

    // Once per scout opened, as soon as its config resolves — the run rollup fills in a beat later
    // off the polled window, so the counts are whatever had loaded by then.
    const detailViewedForRef = useRef<string | null>(null)
    useEffect(() => {
        if (!config || detailViewedForRef.current === skillName) {
            return
        }
        detailViewedForRef.current = skillName
        captureScoutDetailViewed({
            skillName,
            scoutOrigin: config.scout_origin,
            enabled: config.enabled,
            emit: config.emit,
            runIntervalMinutes: config.run_interval_minutes,
            runCount: rollup?.runCount ?? 0,
            failedRunCount: rollup?.failedCount ?? 0,
            emittedSignalCount: rollup?.emittedCount ?? 0,
        })
    }, [skillName, config, rollup])

    if (scoutConfigs === null) {
        // Configs unresolved — never an empty fleet, which is `[]`. While the fetch is in flight
        // (the fleet logic starts it on mount, so a fresh deep link is loading from its first
        // render), hold a skeleton so "Scout not found" can't flash before we have the fleet to
        // look in. Once it has failed, say so and offer a retry. The back link stays either way.
        return (
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-4 py-3">
                <div className="flex">
                    <BackToScouts />
                </div>
                {scoutConfigsLoading ? (
                    <>
                        <LemonSkeleton className="h-24 w-full rounded" />
                        <LemonSkeleton className="h-40 w-full rounded" />
                    </>
                ) : (
                    <div className="flex items-center gap-3 rounded border border-danger bg-danger-highlight px-4 py-3.5">
                        <span className="flex-1 text-xs text-danger">
                            Couldn't load this scout. The scout API may be unavailable or this project may not be
                            enrolled yet.
                        </span>
                        <LemonButton type="secondary" size="small" status="danger" onClick={() => loadScoutConfigs()}>
                            Retry
                        </LemonButton>
                    </div>
                )}
            </div>
        )
    }

    if (config === null) {
        return (
            <div className="flex min-h-0 flex-1 flex-col overflow-auto px-4 py-3">
                <div className="flex">
                    <BackToScouts />
                </div>
                <div className="flex flex-1 items-center justify-center text-sm text-tertiary">Scout not found.</div>
            </div>
        )
    }

    return (
        <div className="flex min-h-0 flex-1 flex-col overflow-auto">
            <div className="flex px-4 pt-3">
                <BackToScouts />
            </div>
            <ScoutDetailHeader
                config={config}
                rollup={rollup}
                noteCount={scoutNotes.length}
                learnedCount={entriesForSkill(entries, skillName).length}
            />

            <div className="grid grid-cols-1 items-start gap-4 px-4 py-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
                <div className="flex min-w-0 flex-col gap-4">
                    <ScoutAttentionBanner config={config} />
                    <ScoutActivitySummary skillName={skillName} />
                    <ScoutReportsSection skillName={skillName} />
                    <ScoutSignalsSection skillName={skillName} />
                    <ScoutRunHistorySection skillName={skillName} />
                </div>
                <div className="flex min-w-0 flex-col gap-4">
                    <ScoutNotesPanel skillName={skillName} />
                    <ScoutLearnedPanel skillName={skillName} />
                </div>
            </div>
        </div>
    )
}

/** Navigation only: the scouts URL handler clears the selected scout, so no action is dispatched here. */
function BackToScouts(): JSX.Element {
    return (
        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.inbox('scouts')} className="w-fit">
            Scouts
        </LemonButton>
    )
}

/** The window's totals in one line, so the sections below don't each restate the same window. */
function ScoutActivitySummary({ skillName }: { skillName: string }): JSX.Element {
    const { rollups } = useValues(scoutFleetLogic)
    const rollup = rollups.get(skillName)

    if (!rollup || rollup.runCount === 0) {
        return <span className="text-sm text-secondary">{SCOUT_NO_RECENT_RUNS}</span>
    }

    // Reports filed lead; reports it only added to are stated as such rather than as a second
    // report count, which read as two flavours of the same number.
    const parts = [
        pluralize(rollup.runCount, 'run'),
        ...(rollup.failedCount > 0 ? [`${rollup.failedCount} failed`] : []),
        ...(rollup.authoredReportIds.size > 0 ? [`${pluralize(rollup.authoredReportIds.size, 'report')} filed`] : []),
        ...(rollup.editedReportIds.size > 0
            ? [`added to ${pluralize(rollup.editedReportIds.size, 'existing report')}`]
            : []),
        ...(rollup.emittedCount > 0 ? [`${pluralize(rollup.emittedCount, 'signal')} emitted`] : []),
    ]

    return (
        <div className="flex flex-col gap-0.5">
            <span className="text-xs font-medium uppercase tracking-wide text-default">
                {SCOUT_RUNS_PER_SCOUT_LABEL}
            </span>
            <span className="text-sm text-secondary">{parts.join(' · ')}</span>
        </div>
    )
}

/**
 * The Reports section: the inbox reports this scout authored or edited directly via the report
 * channel (`emit_report` / `edit_report`) in the recent window, newest-updated first. Distinct from
 * the Signals section, which lists weak `emit_signal` findings. Hidden entirely for the common scout
 * that never authors a report, so it only appears for report-channel scouts.
 */
function ScoutReportsSection({ skillName }: { skillName: string }): JSX.Element | null {
    const { reportRows, touchedReports, scoutReportsLoading, scoutRunsLoadedOnce } = useValues(
        scoutDetailLogic({ skillName })
    )

    // Most scouts never author a report — keep the section out entirely rather than show an empty box.
    if (touchedReports.length === 0) {
        return null
    }

    const loading = !scoutRunsLoadedOnce || (scoutReportsLoading && reportRows.length === 0)
    const editedAny = reportRows.some(({ action }) => action === 'edited')

    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-default">
                {editedAny ? 'Reports it filed or added to' : 'Reports it filed'}
            </span>
            {loading ? (
                <LemonSkeleton className="h-12 w-full rounded" />
            ) : reportRows.length === 0 ? (
                // Touched ids exist but none resolved — the reports were deleted, or the fetch failed.
                <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                    Couldn’t load the reports this scout authored.
                </div>
            ) : (
                reportRows.map(({ report, action }) => (
                    <ScoutReportCard key={report.id} report={report} action={action} />
                ))
            )}
        </div>
    )
}

/**
 * The Signals section: every finding this scout emitted in the recent window, newest first.
 * Emissions are fetched per emitted run by `scoutDetailLogic` (keyed by skill) off the fleet's
 * already-polled runs window. Most runs are quiet — and scouts are moving to the report channel —
 * so the section is hidden entirely when nothing emitted, rather than showing an empty box.
 */
function ScoutSignalsSection({ skillName }: { skillName: string }): JSX.Element | null {
    const { emissionRows, emissionsLoading, emissionsLoadFailed, emittedRuns, scoutRunsLoadedOnce } = useValues(
        scoutDetailLogic({ skillName })
    )
    const { selectedScoutFindingId } = useValues(inboxSceneLogic)

    // No run in this scout's window emitted anything — keep the section out entirely rather than show an
    // empty box (mirrors the Reports section above). Only once the runs window has settled, though:
    // before that, `emittedRuns` is empty by default and hiding would skip the loading skeleton
    // for scouts that do have signals.
    if (scoutRunsLoadedOnce && emittedRuns.length === 0) {
        return null
    }

    // "Loading" until the fleet's per-scout runs have settled once AND this scout's emissions have
    // resolved — otherwise a fresh deep-link would flash the empty state before we know the
    // emitted runs. Gating on the fleet's first-load flag (not its per-poll loading) keeps the
    // quiet-scout empty state from flickering to a skeleton every 60s poll.
    const loading = !scoutRunsLoadedOnce || emissionsLoading
    const hasRows = emissionRows.length > 0
    // The unique emission the deep-link resolves to: the newest row whose finding matches.
    const deepLinkedEmissionId = selectedScoutFindingId
        ? (emissionRows.find(({ emission }) => emission.finding_id === selectedScoutFindingId)?.emission.id ?? null)
        : null

    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-default">Signals</span>
            {loading && !hasRows ? (
                <LemonSkeleton className="h-12 w-full rounded" />
            ) : emissionsLoadFailed && !hasRows ? (
                // Every per-run emissions fetch failed while the rollup says these runs emitted —
                // don't claim "no signals". The 60s poll keeps retrying.
                <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                    Couldn’t load signals for this scout. Retrying…
                </div>
            ) : !hasRows ? (
                <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                    {`No signals emitted in the ${SCOUT_RUNS_PER_SCOUT_LABEL}.`}
                </div>
            ) : (
                emissionRows.map(({ emission, run, report }) => (
                    <ScoutEmissionCard
                        key={emission.id}
                        skillName={skillName}
                        emission={emission}
                        run={run}
                        report={report}
                        // `finding_id` repeats across runs (it's a dedup trace id, not unique), so only
                        // mark the newest matching emission — rows are newest-first — to keep the
                        // highlight/scroll deterministic for a single shared link.
                        isDeepLinked={emission.id === deepLinkedEmissionId}
                    />
                ))
            )}
        </div>
    )
}
