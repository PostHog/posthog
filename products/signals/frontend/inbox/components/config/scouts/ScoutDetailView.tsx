import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { captureScoutAction, captureScoutDetailViewed } from '../../../inboxAnalytics'
import { inboxSceneLogic, ScoutDetailTab } from '../../../inboxSceneLogic'
import { scoutDetailLogic } from '../../../logics/scoutDetailLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutNotesLogic } from '../../../logics/scoutNotesLogic'
import { entriesForSkill, scratchpadLogic } from '../../../logics/scratchpadLogic'
import { ScoutRunFilter, SCOUT_RUNS_PER_SCOUT_LABEL } from '../../../utils/scoutRunsWindow'
import { ScoutAttentionBanner, ScoutDetailHeader } from './ScoutDetailHeader'
import { ScoutEmissionCard } from './ScoutEmissionCard'
import { ScoutLearnedPanel } from './ScoutLearnedPanel'
import { LeaveScoutNoteButton, ScoutNotesPanel } from './ScoutNotesPanel'
import { ScoutReportCard } from './ScoutReportCard'
import { ScoutRunFilterPills, ScoutRunHistorySection } from './ScoutRunHistorySection'

/** The two panes that sit in the right rail at full width, and join the main tab bar below it. */
const RAIL_TABS: ScoutDetailTab[] = ['told', 'learned']

function isRailTab(tab: ScoutDetailTab): boolean {
    return RAIL_TABS.includes(tab)
}

/**
 * One scout's page, at `/inbox/scouts/:skillName`. The header says whether the scout is worth
 * keeping on; tabs below it hold what it produced (Reports, Runs, Signals) and what it carries
 * (Told, Learned). Configuration lives behind the header's settings modal — this page is for
 * reading the scout, not adjusting it.
 *
 * Tabs rather than stacked sections because the sections restated each other's numbers and an
 * uncapped report list pushed the run history — the reason most people open the page — off the
 * first screen.
 */
export function ScoutDetailView({ skillName }: { skillName: string }): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading, rollups } = useValues(scoutFleetLogic)
    const { startRunsPolling, stopRunsPolling, loadScoutConfigs } = useActions(scoutFleetLogic)
    const { entries } = useValues(scratchpadLogic)
    const { scoutNotes } = useValues(scoutNotesLogic({ skillName }))
    const { touchedReports, emissionRows, scoutRunsLoadedOnce } = useValues(scoutDetailLogic({ skillName }))
    const { scoutDetailTab } = useValues(inboxSceneLogic)
    const { setScoutDetailTab } = useActions(inboxSceneLogic)
    const [runFilter, setRunFilter] = useState<ScoutRunFilter>('all')
    // Above the breakpoint both tab bars are on screen, so a click in one has to leave the other
    // where it was. The URL has room for one pane, the one the last click opened, so each column
    // also keeps its own last pane here. Following the URL rather than the click keeps these right
    // through a Back press, which moves the pane without going through the bar.
    const [mainColumnTab, setMainColumnTab] = useState<ScoutDetailTab | null>(null)
    const [railColumnTab, setRailColumnTab] = useState<ScoutDetailTab>('told')
    useEffect(() => {
        if (!scoutDetailTab) {
            return
        }
        if (isRailTab(scoutDetailTab)) {
            setRailColumnTab(scoutDetailTab)
        } else {
            setMainColumnTab(scoutDetailTab)
        }
    }, [scoutDetailTab])

    // Deep-linking straight to a scout (or a narrow viewport where the roster isn't mounted)
    // means nobody else is polling the runs window, so the header + rollup would read empty
    // defaults. Drive the same start/stop lifecycle the roster uses.
    useEffect(() => {
        startRunsPolling()
        return () => stopRunsPolling()
    }, [startRunsPolling, stopRunsPolling])

    const config = scoutConfigs?.find((c) => c.skill_name === skillName) ?? null
    const rollup = rollups.get(skillName)
    const learnedCount = entriesForSkill(entries, skillName).length
    const reportCount = touchedReports.length
    // Reports leads for a scout that files them, because that is what the scout is for; Runs leads
    // for the rest. Held until the runs window settles, so the default doesn't move under a reader
    // a beat after the page opens.
    const defaultMainTab: ScoutDetailTab = !scoutRunsLoadedOnce || reportCount > 0 ? 'reports' : 'runs'
    const tab = scoutDetailTab ?? defaultMainTab

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

    // A scout that files nothing opens Runs with no click, so counting switch_detail_tab alone
    // would miss the pane most readers land on. Held until the runs window settles, because the
    // default reads Reports until then. Same property key as the switch, so one breakdown covers
    // both ways of arriving at a pane.
    const openTabCapturedForRef = useRef<string | null>(null)
    useEffect(() => {
        if (!config || !scoutRunsLoadedOnce || openTabCapturedForRef.current === skillName) {
            return
        }
        openTabCapturedForRef.current = skillName
        captureScoutAction({
            actionType: 'open_detail_tab',
            surface: 'scout_detail',
            skillName,
            extra: { filter: tab },
        })
    }, [skillName, config, scoutRunsLoadedOnce, tab])

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

    const signalCount = emissionRows.length
    const runCount = rollup?.runs.length ?? 0
    const windowEmittedCount = rollup?.emittedCount ?? 0
    const mainTab = isRailTab(tab) ? (mainColumnTab ?? defaultMainTab) : tab
    const railTab = isRailTab(tab) ? tab : railColumnTab

    const switchTab = (next: ScoutDetailTab): void => {
        captureScoutAction({
            actionType: 'switch_detail_tab',
            surface: 'scout_detail',
            skillName,
            extra: { filter: next },
        })
        setScoutDetailTab(next)
    }

    // Reports and Signals hide once the window has settled and says the scout has none of them —
    // the same rule the stacked sections used, now applied to the tab rather than the section.
    // Signals asks the runs window, not the emissions fetched per run: those land a beat later and
    // can fail outright, and hiding the tab then would say the scout emitted nothing while its
    // panel is the only place that reports the failed fetch. Whichever pane is open also keeps its
    // tab, so a link naming a pane this scout has none of still has a tab to select.
    const mainTabs = [
        (!scoutRunsLoadedOnce || reportCount > 0 || mainTab === 'reports') && {
            key: 'reports' as ScoutDetailTab,
            label: `Reports ${reportCount}`,
        },
        { key: 'runs' as ScoutDetailTab, label: `Runs ${runCount}` },
        (!scoutRunsLoadedOnce || windowEmittedCount > 0 || mainTab === 'signals') && {
            key: 'signals' as ScoutDetailTab,
            // The window's count stands in until the rows land, so a failed fetch is not labelled
            // zero beside a panel that says the fetch failed.
            label: `Signals ${signalCount > 0 ? signalCount : windowEmittedCount}`,
        },
    ]
    const railTabs = [
        { key: 'told' as ScoutDetailTab, label: `Told ${scoutNotes.length}` },
        { key: 'learned' as ScoutDetailTab, label: `Learned ${learnedCount}` },
    ]

    const mainPanel = (which: ScoutDetailTab): JSX.Element =>
        which === 'runs' ? (
            <ScoutRunHistorySection skillName={skillName} filter={runFilter} />
        ) : which === 'signals' ? (
            <ScoutSignalsPanel skillName={skillName} />
        ) : (
            <ScoutReportsPanel skillName={skillName} />
        )

    const railPanel = (which: ScoutDetailTab): JSX.Element =>
        which === 'learned' ? <ScoutLearnedPanel skillName={skillName} /> : <ScoutNotesPanel skillName={skillName} />

    return (
        <div className="@container flex min-h-0 flex-1 flex-col overflow-auto">
            <ScoutDetailHeader
                config={config}
                rollup={rollup}
                noteCount={scoutNotes.length}
                learnedCount={learnedCount}
            />

            <div className="grid grid-cols-1 items-start gap-4 px-4 py-4 @4xl:grid-cols-[minmax(0,1fr)_20rem]">
                <div className="flex min-w-0 flex-col gap-4">
                    <ScoutAttentionBanner config={config} />

                    {/* Two tab bars for the same state: below the breakpoint the rail's panes have
                        nowhere to sit, so they join this bar rather than stacking under the run
                        list where nobody scrolls to them. */}
                    <div className="flex flex-col gap-1 @4xl:hidden">
                        <LemonTabs
                            activeKey={tab}
                            onChange={switchTab}
                            size="small"
                            tabs={[...mainTabs, ...railTabs]}
                        />
                        {/* The open pane's control gets its own row here rather than the bar's
                            right slot. This bar carries five tabs, and the slot does not shrink:
                            it pins over the tab strip and hides the rail tabs behind it. The note
                            button is repeated from the rail bar because the rail column itself is
                            not rendered at this width, which would leave the pane unwritable. */}
                        {tab === 'runs' && (
                            <ScoutRunFilterPills skillName={skillName} filter={runFilter} onChange={setRunFilter} />
                        )}
                        {tab === 'told' && (
                            <div className="flex">
                                <LeaveScoutNoteButton skillName={skillName} size="xsmall" />
                            </div>
                        )}
                    </div>
                    <div className="hidden @4xl:block">
                        <LemonTabs
                            activeKey={mainTab}
                            onChange={switchTab}
                            size="small"
                            tabs={mainTabs}
                            rightSlot={
                                mainTab === 'runs' ? (
                                    <ScoutRunFilterPills
                                        skillName={skillName}
                                        filter={runFilter}
                                        onChange={setRunFilter}
                                    />
                                ) : undefined
                            }
                        />
                    </div>

                    {isRailTab(tab) ? (
                        <>
                            <div className="@4xl:hidden">{railPanel(tab)}</div>
                            <div className="hidden @4xl:block">{mainPanel(mainTab)}</div>
                        </>
                    ) : (
                        mainPanel(tab)
                    )}
                </div>

                <div className="hidden min-w-0 flex-col gap-4 @4xl:flex">
                    <LemonTabs
                        activeKey={railTab}
                        onChange={switchTab}
                        size="small"
                        tabs={railTabs}
                        rightSlot={
                            railTab === 'told' ? (
                                <LeaveScoutNoteButton skillName={skillName} size="xsmall" />
                            ) : undefined
                        }
                    />
                    {railPanel(railTab)}
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

/**
 * The Reports tab: the inbox reports this scout authored or edited directly via the report channel
 * (`emit_report` / `edit_report`) in the recent window, newest-updated first. The list is never
 * trimmed for length, because the tab keeps it from pushing anything away, but the per-id fetch
 * behind it is capped, so the panel says how many of the tab's count it is holding.
 */
function ScoutReportsPanel({ skillName }: { skillName: string }): JSX.Element {
    const { reportRows, touchedReports, scoutReportsLoading, scoutRunsLoadedOnce } = useValues(
        scoutDetailLogic({ skillName })
    )
    const { loadScoutReports } = useActions(scoutDetailLogic({ skillName }))

    if (!scoutRunsLoadedOnce || (scoutReportsLoading && reportRows.length === 0)) {
        return <LemonSkeleton className="h-12 w-full rounded" />
    }

    if (reportRows.length === 0) {
        // The runs name the reports, and a separate fetch resolves each one by id. When the runs
        // name some and none resolve, the reports were deleted or the fetch failed, so an empty
        // state would deny the count the tab above it is showing. Nothing refetches on its own
        // here: the touched set is unchanged, so its subscription doesn't fire again.
        if (touchedReports.length > 0) {
            return (
                <div className="flex items-center gap-3 rounded border border-danger bg-danger-highlight px-4 py-3.5">
                    <span className="flex-1 text-xs text-danger">
                        Couldn't load the reports this scout filed or added to. They may have been deleted, or the
                        request failed.
                    </span>
                    <LemonButton type="secondary" size="small" status="danger" onClick={() => loadScoutReports()}>
                        Retry
                    </LemonButton>
                </div>
            )
        }
        return (
            <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                {`No reports filed or added to in the ${SCOUT_RUNS_PER_SCOUT_LABEL}.`}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {/* The tab counts every report the runs name, while this list holds the ones a bounded
                by-id fetch resolved. Say so when they differ, rather than leaving the reader to
                count the cards against the tab. */}
            {!scoutReportsLoading && reportRows.length < touchedReports.length && (
                <span className="text-xs text-muted">
                    {`Showing ${reportRows.length} of ${touchedReports.length} reports.`}
                </span>
            )}
            {reportRows.map(({ report, action }) => (
                <ScoutReportCard key={report.id} report={report} action={action} />
            ))}
        </div>
    )
}

/**
 * The Signals tab: every finding this scout emitted in the recent window, newest first. Emissions
 * are fetched per emitted run by `scoutDetailLogic` (keyed by skill) off the fleet's already-polled
 * runs window.
 */
function ScoutSignalsPanel({ skillName }: { skillName: string }): JSX.Element {
    const { emissionRows, emissionsLoading, emissionsLoadFailed, scoutRunsLoadedOnce } = useValues(
        scoutDetailLogic({ skillName })
    )
    const { loadEmissions } = useActions(scoutDetailLogic({ skillName }))
    const { selectedScoutFindingId } = useValues(inboxSceneLogic)

    // "Loading" until the fleet's per-scout runs have settled once AND this scout's emissions have
    // resolved — otherwise a fresh deep-link would flash the empty state before we know the
    // emitted runs.
    const hasRows = emissionRows.length > 0
    if ((!scoutRunsLoadedOnce || emissionsLoading) && !hasRows) {
        return <LemonSkeleton className="h-12 w-full rounded" />
    }

    if (!hasRows) {
        // Every per-run emissions fetch failed while the rollup says these runs emitted, so don't
        // claim "no signals". Nothing comes back on its own: the emitted runs are unchanged, so the
        // key their subscription watches holds, and the runs poll refetches only the report links.
        if (emissionsLoadFailed) {
            return (
                <div className="flex flex-col items-center gap-2 rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                    <span>Couldn't load signals for this scout.</span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => loadEmissions()}
                        loading={emissionsLoading}
                    >
                        Retry
                    </LemonButton>
                </div>
            )
        }
        return (
            <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                {`No signals emitted in the ${SCOUT_RUNS_PER_SCOUT_LABEL}.`}
            </div>
        )
    }

    // `finding_id` repeats across runs (it's a dedup trace id, not unique), so only mark the newest
    // matching emission — rows are newest-first — to keep the highlight/scroll deterministic for a
    // single shared link.
    const deepLinkedEmissionId = selectedScoutFindingId
        ? (emissionRows.find(({ emission }) => emission.finding_id === selectedScoutFindingId)?.emission.id ?? null)
        : null

    return (
        <div className="flex flex-col gap-2">
            {emissionRows.map(({ emission, run, report }) => (
                <ScoutEmissionCard
                    key={emission.id}
                    skillName={skillName}
                    emission={emission}
                    run={run}
                    report={report}
                    isDeepLinked={emission.id === deepLinkedEmissionId}
                />
            ))}
        </div>
    )
}
