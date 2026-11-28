import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api, { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { reconcileById } from 'lib/utils/objects'

import {
    signalsScoutRunsEmissionReports,
    signalsScoutRunsEmissions,
    signalsScoutRunsList,
    signalsScoutRunsRecentEmissions,
} from 'products/signals/frontend/generated/api'
import type { SignalsScoutRunsListParams } from 'products/signals/frontend/generated/api.schemas'

import { captureScoutAction } from '../inboxAnalytics'
import {
    LinkedSignalReport,
    SignalReport,
    SignalScoutEmission,
    SignalScoutEmissionReportLink,
    SignalScoutRunSummary,
} from '../types'
import {
    oldestRun,
    runFilterQuery,
    runReportActivity,
    SCOUT_RUNS_PER_SCOUT,
    type ScoutRollup,
    type ScoutRunFilter,
} from '../utils/scoutRunsWindow'
import { isReportUnreachable, rememberUnreachableReport } from '../utils/unreachableReports'
import { scoutFleetLogic } from './scoutFleetLogic'

export interface ScoutDetailLogicProps {
    skillName: string
}

/** How a scout touched a report through the report channel: authored it (`emit_report`) or only edited
 * an existing one (`edit_report`). Authoring supersedes a later edit of the same report. */
export type ScoutReportAction = 'authored' | 'edited'

/** A report this scout authored or edited in the window, paired with how it touched it. */
export interface ScoutReportRow {
    report: SignalReport
    action: ScoutReportAction
}

export type ScoutHistoryTab = 'runs' | 'reports' | 'signals'

/**
 * One tab's history older than the polled window. `runs` is every run its pages returned, which is
 * also where the next page's cursor comes from. `exhausted` turns true once a page comes back short.
 */
export interface OlderRunPages {
    runs: SignalScoutRunSummary[]
    pageCount: number
    exhausted: boolean
}

export interface OlderReportPages extends OlderRunPages {
    reports: SignalReport[]
}

export interface OlderSignalPages extends OlderRunPages {
    rows: ScoutEmissionRow[]
}

// A report-authoring scout could in theory touch many reports across the window; bound the per-report
// fetch fan-out the same way emissions are bounded.
const MAX_TOUCHED_REPORTS = 50

// A noisy scout on the 30-minute floor can rack up hundreds of emitted runs across the window;
// fetching emissions for all of them at once would fan out hundreds of concurrent requests and
// render hundreds of markdown cards. Bound both to the most recent N emitted runs — older
// findings live on in the inbox reports they produced.
const MAX_EMITTED_RUNS = 50

// Report linkage is eventually consistent: a finding's signal is grouped into a report asynchronously
// after the run emits it, so the reverse lookup can return `report: null` right after emission and
// resolve minutes later. The emissions themselves are stable once a run completes, so the
// `emittedRunsKey` subscription never refires for them — but the report links need to keep retrying.
// We re-fetch them on the fleet's existing 60s runs-window poll, but only while a *recent* finding is
// still unlinked. Past this window the remaining nulls are findings that will never group (deduped,
// deleted, or below the report threshold), so we stop polling for them.
const REPORT_LINK_RETRY_WINDOW_MINUTES = 30

const OLDER_PAGE_SIZE = SCOUT_RUNS_PER_SCOUT

// The Signals tab pages through runs that produced output, and a run that only filed a report has no
// finding to show. One click reads up to this many pages, so it shows something without crawling a
// report-heavy scout's whole history.
const MAX_SIGNAL_PAGES_PER_LOAD = 4

const NO_OLDER_PAGES: OlderRunPages = { runs: [], pageCount: 0, exhausted: false }

/** An emitted finding paired with the run that produced it (for the run-level task link) and the
 * inbox report its signal grouped into, if any (for the "In report" deep-link chip). */
export interface ScoutEmissionRow {
    emission: SignalScoutEmission
    run: SignalScoutRunSummary
    report: LinkedSignalReport | null
}

function appendNewRuns(existing: SignalScoutRunSummary[], incoming: SignalScoutRunSummary[]): SignalScoutRunSummary[] {
    const seen = new Set(existing.map((run) => run.run_id))
    return [...existing, ...incoming.filter((run) => !seen.has(run.run_id))]
}

function newestFirst(a: SignalScoutRunSummary, b: SignalScoutRunSummary): number {
    return b.created_at.localeCompare(a.created_at) || b.run_id.localeCompare(a.run_id)
}

async function fetchOlderRuns(
    skillName: string,
    loaded: SignalScoutRunSummary[],
    filters: Pick<SignalsScoutRunsListParams, 'emitted' | 'status' | 'touched_report'>
): Promise<SignalScoutRunSummary[]> {
    const cursor = oldestRun(loaded)
    return await signalsScoutRunsList(String(ApiConfig.getCurrentProjectId()), {
        skill_name: skillName,
        limit: OLDER_PAGE_SIZE,
        ...(cursor ? { date_to: cursor.created_at, before_id: cursor.run_id } : {}),
        ...filters,
    })
}

/** Each report these runs touched, in the order the runs list them. Authoring supersedes an edit. */
function touchedReportActions(runs: SignalScoutRunSummary[]): Map<string, ScoutReportAction> {
    const byId = new Map<string, ScoutReportAction>()
    for (const run of runs) {
        const { authored, edited } = runReportActivity(run)
        for (const id of edited) {
            if (!byId.has(id)) {
                byId.set(id, 'edited')
            }
        }
        for (const id of authored) {
            byId.set(id, 'authored')
        }
    }
    return byId
}

async function fetchReports(ids: string[]): Promise<SignalReport[]> {
    // nosemgrep: prefer-codegen-api-namespaced-signals -- the generated retrieve returns `SignalReportApi`, which `ScoutReportCard` does not accept yet
    const settled = await Promise.allSettled(ids.map((id) => api.signalReports.get(id)))
    settled.forEach((result, index) => {
        if (result.status === 'rejected') {
            rememberUnreachableReport(ids[index], result.reason)
        }
    })
    return settled
        .filter((result): result is PromiseFulfilledResult<SignalReport> => result.status === 'fulfilled')
        .map((result) => result.value)
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scoutDetailLogicValues {
    fleetScoutRunsLoadedOnce: boolean // scoutFleetLogic
    rollups: Map<string, ScoutRollup> // scoutFleetLogic
    scoutRunsCoverFleet: boolean // scoutFleetLogic
    emissionReports: SignalScoutEmissionReportLink[]
    emissionReportsLoading: boolean
    emissionRows: ScoutEmissionRow[]
    emissions: SignalScoutEmission[]
    emissionsLoadFailed: boolean
    emissionsLoading: boolean
    emittedRuns: SignalScoutRunSummary[]
    emittedRunsKey: string
    hasOlderPages: boolean
    historyRuns: SignalScoutRunSummary[]
    liveWindowRuns: SignalScoutRunSummary[]
    olderHistoryMayExist: Record<ScoutHistoryTab, boolean>
    olderReports: OlderReportPages
    olderReportsLoading: boolean
    olderRuns: OlderRunPages
    olderRunsLoading: boolean
    olderSignals: OlderSignalPages
    olderSignalsLoading: boolean
    ownRunsLoaded: boolean
    reportActions: Map<string, ScoutReportAction>
    reportBySourceId: Map<string, LinkedSignalReport>
    reportRows: ScoutReportRow[]
    retainedWindowRuns: SignalScoutRunSummary[]
    runFilter: ScoutRunFilter
    scoutHasSignals: boolean | null
    scoutHasSignalsLoading: boolean
    scoutReports: SignalReport[]
    scoutReportsLoading: boolean
    scoutRunsCoverScout: boolean
    scoutRunsLoadedOnce: boolean
    touchedReportCount: number
    touchedReports: {
        action: ScoutReportAction
        id: string
    }[]
    touchedReportsKey: string
    windowEmissionRows: ScoutEmissionRow[]
    windowRuns: SignalScoutRunSummary[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scoutDetailLogicActions {
    loadScoutRunsForSkill: (skillName: string) => string // scoutFleetLogic
    checkScoutHasSignals: () => any
    checkScoutHasSignalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    checkScoutHasSignalsSuccess: (
        scoutHasSignals: boolean,
        payload?: any
    ) => {
        scoutHasSignals: boolean
        payload?: any
    }
    loadEmissionReports: () => any
    loadEmissionReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadEmissionReportsSuccess: (
        emissionReports: SignalScoutEmissionReportLink[],
        payload?: any
    ) => {
        emissionReports: SignalScoutEmissionReportLink[]
        payload?: any
    }
    loadEmissions: () => any
    loadEmissionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadEmissionsSuccess: (
        emissions: SignalScoutEmission[],
        payload?: any
    ) => {
        emissions: SignalScoutEmission[]
        payload?: any
    }
    loadOlder: (tab: ScoutHistoryTab) => {
        tab: ScoutHistoryTab
    }
    loadOlderReports: () => any
    loadOlderReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadOlderReportsSuccess: (
        olderReports: OlderReportPages,
        payload?: any
    ) => {
        olderReports: OlderReportPages
        payload?: any
    }
    loadOlderRuns: () => any
    loadOlderRunsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadOlderRunsSuccess: (
        olderRuns: OlderRunPages,
        payload?: any
    ) => {
        olderRuns: OlderRunPages
        payload?: any
    }
    loadOlderSignals: () => any
    loadOlderSignalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadOlderSignalsSuccess: (
        olderSignals: OlderSignalPages,
        payload?: any
    ) => {
        olderSignals: OlderSignalPages
        payload?: any
    }
    loadScoutReports: () => any
    loadScoutReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadScoutReportsSuccess: (
        scoutReports: SignalReport[],
        payload?: any
    ) => {
        scoutReports: SignalReport[]
        payload?: any
    }
    retainDroppedWindowRuns: (runs: SignalScoutRunSummary[]) => {
        runs: SignalScoutRunSummary[]
    }
    setRunFilter: (filter: ScoutRunFilter) => {
        filter: ScoutRunFilter
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scoutDetailLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        scoutRunsLoadedOnce: (fleetScoutRunsLoadedOnce: boolean, ownRunsLoaded: boolean) => boolean
        scoutRunsCoverScout: (scoutRunsCoverFleet: boolean, ownRunsLoaded: boolean) => boolean
        liveWindowRuns: (rollups: Map<string, ScoutRollup>, arg: any) => SignalScoutRunSummary[]
        windowRuns: (
            liveWindowRuns: SignalScoutRunSummary[],
            retainedWindowRuns: SignalScoutRunSummary[]
        ) => SignalScoutRunSummary[]
        hasOlderPages: (
            olderRuns: OlderRunPages,
            olderReports: OlderReportPages,
            olderSignals: OlderSignalPages
        ) => boolean
        olderHistoryMayExist: (
            liveWindowRuns: SignalScoutRunSummary[],
            olderRuns: OlderRunPages,
            olderReports: OlderReportPages,
            olderSignals: OlderSignalPages
        ) => Record<ScoutHistoryTab, boolean>
        historyRuns: (windowRuns: SignalScoutRunSummary[], olderRuns: OlderRunPages) => SignalScoutRunSummary[]
        emittedRuns: (windowRuns: SignalScoutRunSummary[]) => SignalScoutRunSummary[]
        emittedRunsKey: (emittedRuns: SignalScoutRunSummary[]) => string
        reportBySourceId: (emissionReports: SignalScoutEmissionReportLink[]) => Map<string, LinkedSignalReport>
        touchedReports: (windowRuns: SignalScoutRunSummary[]) => {
            action: ScoutReportAction
            id: string
        }[]
        touchedReportsKey: (
            touchedReports: {
                action: ScoutReportAction
                id: string
            }[]
        ) => string
        reportActions: (
            touchedReports: {
                action: ScoutReportAction
                id: string
            }[],
            olderReports: OlderReportPages
        ) => Map<string, ScoutReportAction>
        touchedReportCount: (reportActions: Map<string, ScoutReportAction>) => number
        reportRows: (
            scoutReports: SignalReport[],
            olderReports: OlderReportPages,
            reportActions: Map<string, ScoutReportAction>
        ) => ScoutReportRow[]
        windowEmissionRows: (
            emissions: SignalScoutEmission[],
            emittedRuns: SignalScoutRunSummary[],
            reportBySourceId: Map<string, LinkedSignalReport>
        ) => ScoutEmissionRow[]
        emissionRows: (windowEmissionRows: ScoutEmissionRow[], olderSignals: OlderSignalPages) => ScoutEmissionRow[]
    }
}

export type scoutDetailLogicType = MakeLogicType<
    scoutDetailLogicValues,
    scoutDetailLogicActions,
    ScoutDetailLogicProps,
    scoutDetailLogicMeta
>

/**
 * Per-scout detail logic, keyed by skill_name. Loads this scout's runs into the singleton
 * `scoutFleetLogic`'s runs window on mount (the fleet poll keeps them fresh after that) to find
 * this scout's emitted runs, then fetches each run's emissions and flattens them into one
 * newest-first list — the Signals section. The runs endpoint has no per-finding listing, so emissions are fetched
 * per emitted run; quiet runs (the vast majority) are never hit.
 *
 * The Runs, Reports and Signals tabs can also page back past that window. Each tab keeps its older
 * pages here, apart from the polled store, so the poll never drops them and the header's numbers keep
 * describing the window.
 */
export const scoutDetailLogic = kea<scoutDetailLogicType>([
    path((key) => ['scenes', 'inbox', 'logics', 'scoutDetailLogic', key]),
    props({} as ScoutDetailLogicProps),
    key((props) => props.skillName),

    connect(() => ({
        values: [
            scoutFleetLogic,
            ['rollups', 'scoutRunsLoadedOnce as fleetScoutRunsLoadedOnce', 'scoutRunsCoverFleet'],
        ],
        actions: [scoutFleetLogic, ['loadScoutRunsForSkill']],
    })),

    actions({
        setRunFilter: (filter: ScoutRunFilter) => ({ filter }),
        loadOlder: (tab: ScoutHistoryTab) => ({ tab }),
        retainDroppedWindowRuns: (runs: SignalScoutRunSummary[]) => ({ runs }),
    }),

    loaders(({ values, props }) => ({
        emissions: [
            [] as SignalScoutEmission[],
            {
                loadEmissions: async (): Promise<SignalScoutEmission[]> => {
                    const runs = values.emittedRuns
                    if (runs.length === 0) {
                        return []
                    }
                    // allSettled, not all: one failed run's fetch (transient 500, deleted run)
                    // shouldn't discard every other run's findings — surface the partial set.
                    const projectId = String(ApiConfig.getCurrentProjectId())
                    const settled = await Promise.allSettled(
                        runs.map((run) => signalsScoutRunsEmissions(projectId, run.run_id))
                    )
                    const fulfilled = settled.filter(
                        (result): result is PromiseFulfilledResult<SignalScoutEmission[]> =>
                            result.status === 'fulfilled'
                    )
                    // Every fetch failed (outage / auth / scope) while the rollup says these runs
                    // emitted — throw so the section shows an error, not a false "no signals". A
                    // partial failure still returns the findings that did load.
                    if (fulfilled.length === 0) {
                        throw new Error('Failed to load scout emissions')
                    }
                    // Reconcile by id so emissions unchanged across polls keep their reference —
                    // `ScoutEmissionCard` is memoized, and fresh references every poll re-render
                    // every card's markdown on an idle page.
                    return reconcileById(
                        values.emissions,
                        fulfilled.flatMap((result) => result.value),
                        (emission) => emission.id
                    )
                },
            },
        ],
        // The reverse "which inbox report did this finding land in" lookup, fetched per emitted run
        // off the same window as the emissions themselves. Best-effort and non-blocking: a finding
        // with no resolved report (not yet grouped, deduped, deleted) simply gets no chip, and a
        // failed fetch leaves the cards as-is rather than erroring the whole section.
        emissionReports: [
            [] as SignalScoutEmissionReportLink[],
            {
                loadEmissionReports: async (): Promise<SignalScoutEmissionReportLink[]> => {
                    const runs = values.emittedRuns
                    if (runs.length === 0) {
                        return []
                    }
                    // Retains the prior round's links per run on failure: this loader is re-run by the
                    // runs-window poll, so blindly keeping only the fulfilled responses would drop a
                    // failed run's already-resolved chips (and an all-rejected retry would clear them
                    // all). source_id is `run:<run_id>:finding:<id>`, so prior links for a run are the
                    // ones prefixed with its run_id.
                    const previous = values.emissionReports
                    const projectId = String(ApiConfig.getCurrentProjectId())
                    const settled = await Promise.allSettled(
                        runs.map((run) => signalsScoutRunsEmissionReports(projectId, run.run_id))
                    )
                    const merged = runs.flatMap((run, index) => {
                        const result = settled[index]
                        if (result.status === 'fulfilled') {
                            return result.value
                        }
                        const prefix = `run:${run.run_id}:`
                        return previous.filter((link) => link.source_id.startsWith(prefix))
                    })
                    // This loader re-runs on every 60s runs-window poll while a recent finding is
                    // unlinked. Reconcile so unchanged links keep their reference — a fresh
                    // `report` object per poll defeats the memo on every emission card.
                    return reconcileById(previous, merged, (link) => link.source_id)
                },
            },
        ],
        // The reports this scout authored/edited directly via the report channel. Unlike findings, the run
        // already carries the report id (no async grouping), so this fetches each report straight by id to
        // resolve its title + live status for the Reports section. Best-effort: a deleted/inaccessible
        // report drops out (its `get` rejects) rather than erroring the section.
        scoutReports: [
            [] as SignalReport[],
            {
                loadScoutReports: async () => {
                    // Ids a previous round found unreachable are dropped before the cap: a deleted
                    // report stays deleted, so re-asking only burns requests and a cached 404 must
                    // not hold a slot a live report could take.
                    const touched = values.touchedReports
                        .filter(({ id }) => !isReportUnreachable(id))
                        .slice(0, MAX_TOUCHED_REPORTS)
                    if (touched.length === 0) {
                        return []
                    }
                    const fetched = await fetchReports(touched.map(({ id }) => id))
                    // Same identity contract as the emissions loaders: unchanged reports across
                    // polls keep their reference so memoized cards don't re-render.
                    return reconcileById(values.scoutReports, fetched, (report) => report.id)
                },
            },
        ],
        // Whether this scout ever emitted a finding, so the Signals tab stays for a scout whose
        // findings are all older than the window. Null until answered, and left null if the check
        // fails, so a failed check never hides the tab.
        scoutHasSignals: [
            null as boolean | null,
            {
                checkScoutHasSignals: async () => {
                    const emissions = await signalsScoutRunsRecentEmissions(String(ApiConfig.getCurrentProjectId()), {
                        skill_name: props.skillName,
                        limit: 1,
                    })
                    return emissions.length > 0
                },
            },
        ],
        // Older runs for the Runs tab, asked for with the open filter pill so a page of the
        // "Failed" pill holds failed runs rather than whatever 25 runs came before the window.
        olderRuns: [
            NO_OLDER_PAGES,
            {
                loadOlderRuns: async (): Promise<OlderRunPages> => {
                    const filter = values.runFilter
                    const previous = values.olderRuns
                    const page = await fetchOlderRuns(
                        props.skillName,
                        [...values.windowRuns, ...previous.runs],
                        runFilterQuery(filter)
                    )
                    if (values.runFilter !== filter) {
                        // The pill changed while the page was in flight, and that already reset the pages.
                        return values.olderRuns
                    }
                    return {
                        runs: appendNewRuns(previous.runs, page),
                        pageCount: previous.pageCount + 1,
                        exhausted: page.length < OLDER_PAGE_SIZE,
                    }
                },
            },
        ],
        // Older reports for the Reports tab: a page of runs that authored or edited a report, then
        // each report those runs name that no loaded page already holds, fetched by id.
        olderReports: [
            { ...NO_OLDER_PAGES, reports: [] } as OlderReportPages,
            {
                loadOlderReports: async (): Promise<OlderReportPages> => {
                    const previous = values.olderReports
                    const page = await fetchOlderRuns(props.skillName, [...values.windowRuns, ...previous.runs], {
                        touched_report: true,
                    })
                    const known = new Set([
                        ...values.touchedReports.map(({ id }) => id),
                        ...previous.reports.map((report) => report.id),
                    ])
                    const pending = [...touchedReportActions(page).keys()]
                        .filter((id) => !known.has(id) && !isReportUnreachable(id))
                        .slice(0, MAX_TOUCHED_REPORTS)
                    const fetched = await fetchReports(pending)
                    return {
                        runs: appendNewRuns(previous.runs, page),
                        reports: [...previous.reports, ...fetched],
                        pageCount: previous.pageCount + 1,
                        exhausted: page.length < OLDER_PAGE_SIZE,
                    }
                },
            },
        ],
        // Older findings for the Signals tab, found the way the window finds them: runs with output,
        // then each emitting run's findings and the reports they grouped into.
        olderSignals: [
            { ...NO_OLDER_PAGES, rows: [] } as OlderSignalPages,
            {
                loadOlderSignals: async (): Promise<OlderSignalPages> => {
                    const previous = values.olderSignals
                    let runs = previous.runs
                    let exhausted = false
                    const emitting: SignalScoutRunSummary[] = []
                    for (
                        let page = 0;
                        page < MAX_SIGNAL_PAGES_PER_LOAD && emitting.length === 0 && !exhausted;
                        page++
                    ) {
                        const pageRuns = await fetchOlderRuns(props.skillName, [...values.windowRuns, ...runs], {
                            emitted: true,
                        })
                        runs = appendNewRuns(runs, pageRuns)
                        exhausted = pageRuns.length < OLDER_PAGE_SIZE
                        emitting.push(...pageRuns.filter((run) => (run.emitted_count ?? 0) > 0))
                    }
                    const projectId = String(ApiConfig.getCurrentProjectId())
                    const [emissionResults, linkResults] = await Promise.all([
                        Promise.allSettled(emitting.map((run) => signalsScoutRunsEmissions(projectId, run.run_id))),
                        Promise.allSettled(
                            emitting.map((run) => signalsScoutRunsEmissionReports(projectId, run.run_id))
                        ),
                    ])
                    // Same rule as the window: when every fetch failed, say so rather than show no
                    // findings for runs that emitted some. The pages are kept back, so a retry reads them again.
                    if (emitting.length > 0 && emissionResults.every((result) => result.status === 'rejected')) {
                        throw new Error('Failed to load older scout emissions')
                    }
                    const reportBySourceId = new Map(
                        linkResults
                            .flatMap((result) => (result.status === 'fulfilled' ? result.value : []))
                            .filter((link) => link.report !== null)
                            .map((link) => [link.source_id, link.report as LinkedSignalReport])
                    )
                    const rows = emitting
                        .flatMap((run, index) => {
                            const result = emissionResults[index]
                            return result.status === 'fulfilled'
                                ? result.value.map((emission) => ({
                                      emission,
                                      run,
                                      report: reportBySourceId.get(emission.source_id) ?? null,
                                  }))
                                : []
                        })
                        .sort((a, b) => (b.emission.emitted_at ?? '').localeCompare(a.emission.emitted_at ?? ''))
                    return {
                        runs,
                        rows: [...previous.rows, ...rows],
                        pageCount: previous.pageCount + 1,
                        exhausted,
                    }
                },
            },
        ],
    })),

    reducers(({ props }) => ({
        // True once this scout's own runs land, so the page renders without the fleet-wide read.
        ownRunsLoaded: [
            false,
            {
                [scoutFleetLogic.actionTypes.loadScoutRunsForSkillSuccess]: (state, { payload }) =>
                    payload === props.skillName ? true : state,
            },
        ],
        // True only when the most recent emissions load failed outright (all per-run fetches
        // rejected). Reset when a fresh load starts or succeeds. Lets the Signals section show a
        // retrying/error state instead of a false empty when findings exist but couldn't be loaded.
        emissionsLoadFailed: [
            false,
            {
                loadEmissions: () => false,
                loadEmissionsSuccess: () => false,
                loadEmissionsFailure: () => true,
            },
        ],
        runFilter: [
            'all' as ScoutRunFilter,
            {
                setRunFilter: (_, { filter }) => filter,
            },
        ],
        // Older run pages hold only the runs that match the pill they were asked for.
        olderRuns: {
            setRunFilter: () => NO_OLDER_PAGES,
        },
        // Runs the poll moved out of the window after older pages were loaded. Kept so the history
        // has no gap between the window and the first older page.
        retainedWindowRuns: [
            [] as SignalScoutRunSummary[],
            {
                retainDroppedWindowRuns: (state, { runs }) => appendNewRuns(state, runs),
            },
        ],
    })),

    selectors({
        // Same "loaded once" contract as the fleet's flag, satisfied by either read.
        scoutRunsLoadedOnce: [
            (s) => [s.fleetScoutRunsLoadedOnce, s.ownRunsLoaded],
            (fleetScoutRunsLoadedOnce: boolean, ownRunsLoaded: boolean): boolean =>
                fleetScoutRunsLoadedOnce || ownRunsLoaded,
        ],
        // The single-scout read always probes this scout, so the fleet probe bound does not apply.
        // The fleet loader keeps this scout's slice when its own response did not probe the scout.
        scoutRunsCoverScout: [
            (s) => [s.scoutRunsCoverFleet, s.ownRunsLoaded],
            (scoutRunsCoverFleet: boolean, ownRunsLoaded: boolean): boolean => scoutRunsCoverFleet || ownRunsLoaded,
        ],
        liveWindowRuns: [
            (s) => [s.rollups, (_, props) => props.skillName],
            (rollups: Map<string, ScoutRollup>, skillName: string): SignalScoutRunSummary[] =>
                rollups.get(skillName)?.runs ?? [],
        ],
        windowRuns: [
            (s) => [s.liveWindowRuns, s.retainedWindowRuns],
            (liveWindowRuns: SignalScoutRunSummary[], retainedWindowRuns: SignalScoutRunSummary[]) =>
                retainedWindowRuns.length > 0 ? appendNewRuns(liveWindowRuns, retainedWindowRuns) : liveWindowRuns,
        ],
        hasOlderPages: [
            (s) => [s.olderRuns, s.olderReports, s.olderSignals],
            (olderRuns: OlderRunPages, olderReports: OlderReportPages, olderSignals: OlderSignalPages): boolean =>
                olderRuns.pageCount + olderReports.pageCount + olderSignals.pageCount > 0,
        ],
        // Whether a tab may have history the page hasn't loaded: its pages aren't exhausted and the
        // window is full. A window that isn't full already holds every run the guard lets through.
        olderHistoryMayExist: [
            (s) => [s.liveWindowRuns, s.olderRuns, s.olderReports, s.olderSignals],
            (
                liveWindowRuns: SignalScoutRunSummary[],
                olderRuns: OlderRunPages,
                olderReports: OlderReportPages,
                olderSignals: OlderSignalPages
            ): Record<ScoutHistoryTab, boolean> => {
                const windowFull = liveWindowRuns.length >= SCOUT_RUNS_PER_SCOUT
                return {
                    runs: windowFull && !olderRuns.exhausted,
                    reports: windowFull && !olderReports.exhausted,
                    signals: windowFull && !olderSignals.exhausted,
                }
            },
        ],
        historyRuns: [
            (s) => [s.windowRuns, s.olderRuns],
            (windowRuns: SignalScoutRunSummary[], olderRuns: OlderRunPages): SignalScoutRunSummary[] =>
                appendNewRuns(windowRuns, olderRuns.runs).sort(newestFirst),
        ],
        // This scout's runs that emitted at least one finding, newest first, capped to the most
        // recent MAX_EMITTED_RUNS. `.filter()` returns a fresh array, so the in-place `.sort()`
        // never touches the shared rollup `runs` the header timeline reads (oldest-first).
        emittedRuns: [
            (s) => [s.windowRuns],
            (windowRuns: SignalScoutRunSummary[]): SignalScoutRunSummary[] =>
                windowRuns
                    .filter((run) => (run.emitted_count ?? 0) > 0)
                    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
                    .slice(0, MAX_EMITTED_RUNS),
        ],
        // Stable string key over the emitted runs — refetch emissions only when the set actually
        // changes, not on every 60s per-scout runs poll that returns the same runs. Includes
        // `emitted_count` so a run that emits more findings while still in progress retriggers.
        emittedRunsKey: [
            (s) => [s.emittedRuns],
            (emittedRuns: SignalScoutRunSummary[]): string =>
                emittedRuns
                    .map((run) => `${run.run_id}:${run.emitted_count ?? 0}`)
                    .sort()
                    .join(','),
        ],
        // source_id -> linked inbox report, for findings that resolved to one. Keyed on source_id
        // (the deterministic `run:<run_id>:finding:<id>` join), which is unique per emission and the
        // exact field the backend reverse-lookup keys on. Findings with a null report are skipped.
        reportBySourceId: [
            (s) => [s.emissionReports],
            (emissionReports: SignalScoutEmissionReportLink[]): Map<string, LinkedSignalReport> =>
                new Map(
                    emissionReports
                        .filter((link) => link.report !== null)
                        .map((link) => [link.source_id, link.report as LinkedSignalReport])
                ),
        ],
        // The distinct reports this scout touched via the report channel in the window, each tagged with
        // how it touched it. Authoring supersedes a later edit of the same report, so a report in both
        // sets reads as "authored".
        touchedReports: [
            (s) => [s.windowRuns],
            (windowRuns: SignalScoutRunSummary[]): { id: string; action: ScoutReportAction }[] =>
                [...touchedReportActions(windowRuns).entries()].map(([id, action]) => ({ id, action })),
        ],
        // Stable key over the touched report set — refetch the reports only when the set actually changes,
        // not on every runs-window poll that returns the same runs.
        touchedReportsKey: [
            (s) => [s.touchedReports],
            (
                touchedReports: {
                    action: ScoutReportAction
                    id: string
                }[]
            ): string =>
                touchedReports
                    .map(({ id, action }) => `${id}:${action}`)
                    .sort()
                    .join(','),
        ],
        reportActions: [
            (s) => [s.touchedReports, s.olderReports],
            (
                touchedReports: { id: string; action: ScoutReportAction }[],
                olderReports: OlderReportPages
            ): Map<string, ScoutReportAction> => {
                const actions = new Map(touchedReports.map(({ id, action }) => [id, action]))
                for (const [id, action] of touchedReportActions(olderReports.runs)) {
                    if (action === 'authored' || !actions.has(id)) {
                        actions.set(id, action)
                    }
                }
                return actions
            },
        ],
        touchedReportCount: [
            (s) => [s.reportActions],
            (reportActions: Map<string, ScoutReportAction>): number => reportActions.size,
        ],
        // The window's reports newest-updated first, then the older pages' reports in the order the
        // scout touched them. A touched id whose report fetch failed (deleted/inaccessible) is skipped.
        reportRows: [
            (s) => [s.scoutReports, s.olderReports, s.reportActions],
            (
                scoutReports: SignalReport[],
                olderReports: OlderReportPages,
                reportActions: Map<string, ScoutReportAction>
            ): ScoutReportRow[] => {
                const toRow = (report: SignalReport): ScoutReportRow | null => {
                    const action = reportActions.get(report.id)
                    return action ? { report, action } : null
                }
                const windowRows = scoutReports
                    .map(toRow)
                    .filter((row): row is ScoutReportRow => row !== null)
                    .sort((a, b) => (b.report.updated_at ?? '').localeCompare(a.report.updated_at ?? ''))
                const windowIds = new Set(windowRows.map(({ report }) => report.id))
                const olderRows = olderReports.reports
                    .filter((report) => !windowIds.has(report.id))
                    .map(toRow)
                    .filter((row): row is ScoutReportRow => row !== null)
                return [...windowRows, ...olderRows]
            },
        ],
        // Join fetched emissions back to their run (for the per-row task-run link) and to the inbox
        // report they grouped into (for the "In report" chip), newest first.
        windowEmissionRows: [
            (s) => [s.emissions, s.emittedRuns, s.reportBySourceId],
            (
                emissions: SignalScoutEmission[],
                emittedRuns: SignalScoutRunSummary[],
                reportBySourceId: Map<string, LinkedSignalReport>
            ): ScoutEmissionRow[] => {
                const runsById = new Map(emittedRuns.map((run) => [run.run_id, run]))
                return emissions
                    .map((emission) => {
                        const run = runsById.get(emission.run_id)
                        return run ? { emission, run, report: reportBySourceId.get(emission.source_id) ?? null } : null
                    })
                    .filter((row): row is ScoutEmissionRow => row !== null)
                    .sort((a, b) => (b.emission.emitted_at ?? '').localeCompare(a.emission.emitted_at ?? ''))
            },
        ],
        emissionRows: [
            (s) => [s.windowEmissionRows, s.olderSignals],
            (windowEmissionRows: ScoutEmissionRow[], olderSignals: OlderSignalPages): ScoutEmissionRow[] => {
                if (olderSignals.rows.length === 0) {
                    return windowEmissionRows
                }
                const seen = new Set(windowEmissionRows.map(({ emission }) => emission.id))
                return [...windowEmissionRows, ...olderSignals.rows.filter(({ emission }) => !seen.has(emission.id))]
            },
        ],
    }),

    subscriptions(({ actions, values }) => ({
        // Fires on mount (empty → real ids once the runs window loads) and whenever the set of
        // emitted runs changes; the string key holds equal across no-op polls so we don't refetch.
        emittedRunsKey: () => {
            actions.loadEmissions()
            actions.loadEmissionReports()
        },
        // Fires on mount (empty → real ids once the runs window loads) and whenever the set of touched
        // reports changes; the key holds equal across no-op polls so we don't refetch.
        touchedReportsKey: () => {
            actions.loadScoutReports()
        },
        // Each older page starts below the oldest loaded run. When a poll moves a run out of the
        // window, keep it, or it would sit between the window and the older pages and never show.
        liveWindowRuns: (next: SignalScoutRunSummary[], previous: SignalScoutRunSummary[] | undefined) => {
            if (!previous || !values.hasOlderPages) {
                return
            }
            const stillLive = new Set(next.map((run) => run.run_id))
            const dropped = previous.filter((run) => !stillLive.has(run.run_id))
            if (dropped.length > 0) {
                actions.retainDroppedWindowRuns(dropped)
            }
        },
    })),

    listeners(({ actions, values, props }) => ({
        // Report grouping resolves asynchronously after emission, so ride the fleet's 60s per-scout
        // runs poll to keep refetching the links — but only while a recently-emitted finding is still
        // unlinked. Computed fresh here (not a memoized selector) so the recency cutoff advances with
        // wall-clock time and a never-grouping finding stops the poll once it ages out of the window.
        [scoutFleetLogic.actionTypes.loadScoutRunsSuccess]: () => {
            const cutoff = dayjs().subtract(REPORT_LINK_RETRY_WINDOW_MINUTES, 'minute')
            const hasRecentUnlinked = values.windowEmissionRows.some(
                (row) =>
                    row.report === null && row.emission.emitted_at && dayjs(row.emission.emitted_at).isAfter(cutoff)
            )
            if (hasRecentUnlinked) {
                actions.loadEmissionReports()
            }
        },
        // `page` is how deep the reader has gone on this tab, which says how much history people need.
        loadOlder: ({ tab }) => {
            const pages =
                tab === 'runs' ? values.olderRuns : tab === 'reports' ? values.olderReports : values.olderSignals
            captureScoutAction({
                actionType: 'load_older',
                surface: 'scout_detail',
                skillName: props.skillName,
                extra: { tab, page: pages.pageCount + 1, ...(tab === 'runs' ? { filter: values.runFilter } : {}) },
            })
            if (tab === 'runs') {
                actions.loadOlderRuns()
            } else if (tab === 'reports') {
                actions.loadOlderReports()
            } else {
                actions.loadOlderSignals()
            }
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadScoutRunsForSkill(props.skillName)
        actions.checkScoutHasSignals()
    }),
])
