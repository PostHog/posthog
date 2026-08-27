import { MakeLogicType, actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import type { CaptureOptions } from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { reconcileById } from 'lib/utils/objects'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Breadcrumb } from '~/types'
import type { UserType } from '~/types'

import { OriginProduct, Task, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'
import { signalsReportsViewedCreate } from 'products/signals/frontend/generated/api'

import {
    captureInboxReportClosed,
    captureInboxReportOpened,
    captureInboxReportScrolled,
    InboxReportCloseMethod,
    InboxReportOpenMethod,
} from './inboxAnalytics'
import { inboxFiltersLogic } from './logics/inboxFiltersLogic'
import { INBOX_REPORT_SECTION_LIST_PARAMS, reportListLogic } from './logics/reportListLogic'
import type { ScoutCreateInitialValues } from './logics/scoutCreateModalLogic'
import { scratchpadLogic } from './logics/scratchpadLogic'
import { signalSourcesLogic } from './signalSourcesLogic'
import {
    INBOX_LEGACY_TAB_KEYS,
    INBOX_STAFF_ONLY_TAB_KEYS,
    INBOX_TAB_KEYS,
    InboxReportSectionKey,
    InboxTabKey,
    SignalReport,
    SignalRun,
    SignalScoutRunStatus,
    SignalScoutRunSummary,
} from './types'
import { isInboxRedesignEnabled } from './utils/inboxRedesign'
import { inboxTabRedirectPath } from './utils/inboxReportUrls'
import { decodeScoutCreateTemplate } from './utils/scoutTemplateDeepLink'

// Newest-first scout runs to pull for the Runs panel. The scout-runs endpoint caps at 100 server-side.
const SCOUT_RUNS_LIMIT = 100

// Signal-pipeline tasks to pull. Bounded symmetrically with the scout side (the tasks endpoint caps
// at 100); passed explicitly so the cap is visible rather than relying on the server default.
const SIGNAL_TASKS_LIMIT = 100

/** Strips `#createScout=` from the URL so a refresh can't re-trigger it, then opens the modal. */
function consumeScoutTemplateHash(
    actions: { setScoutTemplateDraft: (draft: ScoutCreateInitialValues | null) => void },
    hashParams: Record<string, any> | undefined
): void {
    const raw = hashParams?.['createScout']
    if (raw === undefined) {
        return
    }
    const { createScout: _consumed, ...remainingHashParams } = hashParams ?? {}
    router.actions.replace(router.values.location.pathname, router.values.searchParams, remainingHashParams)
    const draft = decodeScoutCreateTemplate(raw)
    if (draft) {
        actions.setScoutTemplateDraft(draft)
    } else {
        lemonToast.error("Couldn't read the scout template from this link")
    }
}

// How often the Runs panel refetches while it's open, so live runs update in place.
const RUNS_POLL_INTERVAL_MS = 5000

// `TaskRunStatus` and `SignalScoutRunStatus` enumerate the same run states. This `Record` keyed on the
// enum makes the relationship exhaustive: a new `TaskRunStatus` value breaks the build here instead of
// silently rendering as 'queued', so the two type vocabularies can't drift unnoticed.
const TASK_RUN_STATUS_TO_SCOUT_STATUS: Record<TaskRunStatus, SignalScoutRunStatus> = {
    [TaskRunStatus.NOT_STARTED]: 'not_started',
    [TaskRunStatus.QUEUED]: 'queued',
    [TaskRunStatus.IN_PROGRESS]: 'in_progress',
    [TaskRunStatus.COMPLETED]: 'completed',
    [TaskRunStatus.FAILED]: 'failed',
    [TaskRunStatus.CANCELLED]: 'cancelled',
}

/**
 * Merge the Runs panel's two sources — scout runs and signal-pipeline tasks — into one newest-first
 * `SignalRun[]`. Pure (no I/O) so the merge/sort/normalize contract is unit-testable directly.
 * Scout runs without a backing `task_id` are dropped (they can't deep-link to a task); signal rows
 * fall back to the task's own timestamp / a null status when no run exists yet.
 *
 * A signal task only counts as a run once it's linked to a report. `origin_product=signal_report`
 * alone is too broad: the scout-authoring CTAs create chat threads under the same origin, and those
 * are a "let's write a scout" conversation, not a pipeline run — listing them here drops the user
 * into a thread with no report to go back to.
 */
export function mergeSignalRuns(scoutRuns: SignalScoutRunSummary[], signalTasks: Task[]): SignalRun[] {
    const scoutRows = scoutRuns
        .filter((run): run is SignalScoutRunSummary & { task_id: string } => !!run.task_id)
        .map(
            (run): SignalRun => ({
                task_id: run.task_id,
                kind: 'scout',
                title: run.skill_name,
                status: run.status,
                report_id: null,
                created_at: run.created_at,
            })
        )
    const signalRows = signalTasks
        .filter((task): task is Task & { signal_report: string } => !!task.signal_report)
        .map((task): SignalRun => {
            const latestStatus = task.latest_run?.status
            return {
                task_id: task.id,
                kind: 'signal',
                title: task.title,
                status: latestStatus ? TASK_RUN_STATUS_TO_SCOUT_STATUS[latestStatus] : null,
                report_id: task.signal_report,
                created_at: task.latest_run?.created_at ?? task.created_at,
            }
        })
    return [...scoutRows, ...signalRows].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
}

/** Whether a URL segment is one of the current layout's page tabs. */
function isInboxTabKey(value: string | undefined, redesign: boolean): value is InboxTabKey {
    const tabKeys = (redesign ? INBOX_TAB_KEYS : INBOX_LEGACY_TAB_KEYS) as string[]
    return value !== undefined && tabKeys.includes(value)
}

function isStaffOnlyTab(tab: string | undefined): boolean {
    return tab !== undefined && (INBOX_STAFF_ONLY_TAB_KEYS as string[]).includes(tab)
}

/**
 * Find a report already loaded in one of the mounted per-view lists, so opening it can render the
 * detail instantly from the list row instead of waiting on a fresh
 * `GET`. The background fetch still runs to converge on the authoritative record.
 */
// A search typed into the scratchpad is transient: reopening the panel later should show the whole
// window again, not the last query. Clear it whenever the scratchpad closes — by any path (close
// button, report/scout open, Back nav).
function clearScratchpadSearch(): void {
    const mounted = scratchpadLogic.findMounted()
    if (mounted?.values.searchText) {
        mounted.actions.setSearchText('')
    }
}

function findLoadedReport(id: string): SignalReport | null {
    for (const sectionKey of Object.keys(INBOX_REPORT_SECTION_LIST_PARAMS) as InboxReportSectionKey[]) {
        const mounted = reportListLogic.findMounted({
            sectionKey,
            listParams: INBOX_REPORT_SECTION_LIST_PARAMS[sectionKey],
        })
        const found = mounted?.values.reports.find((r: SignalReport) => r.id === id)
        if (found) {
            return found
        }
    }
    return null
}

/**
 * Position (1-based) and size of the report's list, for `Inbox report opened`. Searches the mounted
 * per-section lists for the report. Null when the report isn't in a loaded list (e.g. a cold deep-link).
 */
function findReportRank(id: string): {
    rank: number | null
    listSize: number | null
    section: InboxReportSectionKey | null
} {
    for (const sectionKey of Object.keys(INBOX_REPORT_SECTION_LIST_PARAMS) as InboxReportSectionKey[]) {
        const mounted = reportListLogic.findMounted({
            sectionKey,
            listParams: INBOX_REPORT_SECTION_LIST_PARAMS[sectionKey],
        })
        const reports = mounted?.values.reports
        if (!reports) {
            continue
        }
        const idx = reports.findIndex((r: SignalReport) => r.id === id)
        if (idx >= 0) {
            return { rank: idx + 1, listSize: reports.length, section: sectionKey }
        }
    }
    return { rank: null, listSize: null, section: null }
}

/**
 * The URL for whichever full-width inbox surface is open, or the list otherwise. The surfaces
 * (report, scout detail, scratchpad, findings, runs, triage) are mutually exclusive, so a fixed
 * priority order resolves them.
 */
function inboxSurfaceUrl(values: {
    selectedReportId: string | null
    activeTab: InboxTabKey
    selectedScoutSkillName: string | null
    selectedScoutFindingId: string | null
    isScratchpadOpen: boolean
    isFindingsOpen: boolean
    isRunsOpen: boolean
    isTriageOpen: boolean
    isRedesign: boolean
}): string {
    if (values.selectedReportId) {
        // Under the redesign every report lives in the one Reports list; the legacy layout keeps the
        // report under the tab that listed it, so its back control returns there.
        return urls.inboxReport(values.isRedesign ? 'reports' : values.activeTab, values.selectedReportId)
    }
    if (values.selectedScoutSkillName) {
        return urls.inboxScout(values.selectedScoutSkillName, values.selectedScoutFindingId ?? undefined)
    }
    if (values.isScratchpadOpen) {
        return urls.inboxScratchpad()
    }
    if (values.isFindingsOpen) {
        return urls.inboxFindings()
    }
    if (values.isRunsOpen) {
        return urls.inboxRuns()
    }
    if (values.isTriageOpen) {
        return urls.inboxTriage()
    }
    return urls.inbox(values.activeTab)
}

/** Open-report engagement tracking state, kept on the logic's `cache` (not reactive). */
interface InboxOpenTracking {
    report: SignalReport
    openedAt: number
    /** Set once the first detail-pane scroll has fired `Inbox report scrolled` for this open. */
    scrolled: boolean
}

/**
 * Emit the dwell-time close for a report still open when the view goes away, then clear the tracking
 * so it can't fire twice. Shared by the scene unmount (`unmount`) and the tab-close flush
 * (`page_unload`); a no-op when no report is open.
 */
function flushOpenReport(
    cache: Record<string, any>,
    closeMethod: InboxReportCloseMethod,
    options?: CaptureOptions
): void {
    const open: InboxOpenTracking | undefined = cache.openTracking
    if (!open) {
        return
    }
    captureInboxReportClosed({ report: open.report, timeSpentMs: Date.now() - open.openedAt, closeMethod }, options)
    cache.openTracking = undefined
}

/**
 * Run the current inbox URL through `urlToAction` again. A `replace` to the unchanged URL still
 * dispatches `locationChanged`, and the scene logic treats an unchanged scene and params as no
 * navigation, so only the route handlers run.
 */
function replayInboxLocation(): void {
    const { pathname, search, hash } = router.values.location
    const path = removeProjectIdIfPresent(pathname)
    if (path !== urls.inbox() && !path.startsWith(`${urls.inbox()}/`)) {
        return
    }
    router.actions.replace(pathname + search + hash)
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxSceneLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    receivedFeatureFlags: boolean // featureFlagLogic
    user: UserType | null // userLogic
    activeTab: InboxTabKey
    activeTabState: InboxTabKey | null
    breadcrumbs: Breadcrumb[]
    isFindingsOpen: boolean
    isRedesign: boolean
    isRunsOpen: boolean
    isScratchpadOpen: boolean
    isStaff: boolean
    isTriageOpen: boolean
    scoutTemplateDraft: ScoutCreateInitialValues | null
    selectedReport: SignalReport | null
    selectedReportId: string | null
    selectedReportLoading: boolean
    selectedReportResponse: SignalReport | null
    selectedReportResponseLoading: boolean
    selectedScoutFindingId: string | null
    selectedScoutSkillName: string | null
    signalRuns: SignalRun[]
    signalRunsLoading: boolean
    signalRunsResponse: SignalRun[] | null
    signalRunsResponseLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxSceneLogicActions {
    setFeatureFlags: (
        flags: string[],
        variants: Record<string, boolean | string>
    ) => {
        flags: string[]
        variants: Record<string, boolean | string>
    } // featureFlagLogic
    loadSourceConfigs: () => any // signalSourcesLogic
    loadRuns: (_payload: void) => void
    loadRunsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRunsSuccess: (
        signalRunsResponse: SignalRun[],
        payload?: void
    ) => {
        signalRunsResponse: SignalRun[]
        payload?: void
    }
    loadSelectedReport: ({ id }: { id: string }) => {
        id: string
    }
    loadSelectedReportFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSelectedReportSuccess: (
        selectedReportResponse: SignalReport | null,
        payload?: {
            id: string
        }
    ) => {
        selectedReportResponse: SignalReport | null
        payload?: {
            id: string
        }
    }
    reportDetailScrolled: () => {
        value: true
    }
    seedSelectedReport: (report: SignalReport | null) => {
        report: SignalReport | null
    }
    setActiveTab: (tab: InboxTabKey) => {
        tab: InboxTabKey
    }
    setFindingsOpen: (open: boolean) => {
        open: boolean
    }
    setRunsOpen: (open: boolean) => {
        open: boolean
    }
    setScoutTemplateDraft: (draft: ScoutCreateInitialValues | null) => {
        draft: ScoutCreateInitialValues | null
    }
    setScratchpadOpen: (open: boolean) => {
        open: boolean
    }
    setSelectedReportId: (
        id: string | null,
        openMethod?: InboxReportOpenMethod
    ) => {
        id: string | null
        openMethod: InboxReportOpenMethod
    }
    setSelectedScoutSkillName: (
        skillName: string | null,
        findingId?: string | null
    ) => {
        findingId: string | null
        skillName: string | null
    }
    setTriageOpen: (open: boolean) => {
        open: boolean
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxSceneLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        isRedesign: (featureFlags: FeatureFlagsSet) => boolean
        activeTab: (activeTabState: InboxTabKey | null, isRedesign: boolean) => InboxTabKey
        isStaff: (user: UserType | null) => boolean
        signalRuns: (signalRunsResponse: SignalRun[] | null) => SignalRun[]
        signalRunsLoading: (signalRunsResponse: SignalRun[] | null, signalRunsResponseLoading: boolean) => boolean
        selectedReport: (selectedReportResponse: SignalReport | null) => SignalReport | null
        selectedReportLoading: (selectedReportResponseLoading: boolean) => boolean
    }
}

export type inboxSceneLogicType = MakeLogicType<
    inboxSceneLogicValues,
    inboxSceneLogicActions,
    Record<string, any>,
    inboxSceneLogicMeta
>

/**
 * Inbox scene orchestrator. Owns the active page tab (Reports / Scouts / Settings), the active
 * Reports view, the selected report (loaded by id), the full-width surfaces that replace the list
 * (scout detail, scratchpad, findings, runs, triage mode), and the project-wide runs list. The
 * per-view report lists + their counts live in the keyed `reportListLogic` (one instance per view).
 */
export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    connect(() => ({
        // Mount inboxFiltersLogic with the scene so its URL sync (shareable filter params) applies on
        // deep-link load, before the filter bar / list have rendered.
        logic: [inboxFiltersLogic],
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags', 'receivedFeatureFlags']],
        actions: [signalSourcesLogic, ['loadSourceConfigs'], featureFlagLogic, ['setFeatureFlags']],
    })),

    actions({
        setSelectedReportId: (id: string | null, openMethod: InboxReportOpenMethod = 'unknown') => ({
            id,
            openMethod,
        }),
        // Seed (or clear) the selected report synchronously from an already-loaded list row, so the
        // detail renders without a spinner while the authoritative fetch runs in the background.
        seedSelectedReport: (report: SignalReport | null) => ({ report }),
        setActiveTab: (tab: InboxTabKey) => ({ tab }),
        // Scout detail surface: selecting a scout opens its full-width detail over the list. An
        // optional finding id deep-links to one emitted finding within that scout (highlighted +
        // scrolled into view if it's still in the recent window).
        setSelectedScoutSkillName: (skillName: string | null, findingId: string | null = null) => ({
            skillName,
            findingId,
        }),
        // Scout fleet-memory (scratchpad) surface: a full-width browse/search view over the list,
        // mutually exclusive with the report and scout-detail views. Reached from the fleet-memory callout.
        setScratchpadOpen: (open: boolean) => ({ open }),
        // Cross-fleet findings surface: full-width browse/search/filter of every finding the troop
        // emitted recently, mutually exclusive with the other full-width views.
        setFindingsOpen: (open: boolean) => ({ open }),
        // Runs surface: the project-wide scout + signal-pipeline runs list, reached from the roster.
        setRunsOpen: (open: boolean) => ({ open }),
        // Triage mode: the Needs-a-decision queue one report at a time, driven from the keyboard.
        setTriageOpen: (open: boolean) => ({ open }),
        // The detail pane was scrolled. The logic fires `Inbox report scrolled` once per open; the
        // component reports the raw scroll.
        reportDetailScrolled: true,
        // A decoded `#createScout=` payload, prefilling the create modal. The user still submits it.
        setScoutTemplateDraft: (draft: ScoutCreateInitialValues | null) => ({ draft }),
    }),

    loaders(({ values }) => ({
        // Runs panel: a newest-first list of scout + signals-pipeline runs, composed from two existing
        // endpoints, scout runs (clean `skill_name`) and signal-pipeline tasks (whose title is the
        // originating report's title). Merged client-side; there is no unified backend "runs" resource
        // by design. Both endpoints are team-scoped and readable by any member, so the panel is public.
        signalRunsResponse: [
            null as SignalRun[] | null,
            {
                loadRuns: async (_payload: void, breakpoint) => {
                    const [scoutResult, signalResult] = await Promise.allSettled([
                        api.signalScout.runs.list({ limit: SCOUT_RUNS_LIMIT }),
                        // `internal: 'all'` so the pipeline's runs (research and implementation, both
                        // created internal) are included. They're hidden from the default task list.
                        api.tasks.list({
                            origin_product: OriginProduct.SIGNAL_REPORT,
                            internal: 'all',
                            limit: SIGNAL_TASKS_LIMIT,
                        }),
                    ])
                    breakpoint()
                    // Degrade gracefully: surface whichever source resolved, matching the inbox's other
                    // fan-out loaders (scoutDetailLogic) so one source's outage doesn't blank the panel.
                    // Only fail the load if both sources rejected.
                    if (scoutResult.status === 'rejected' && signalResult.status === 'rejected') {
                        throw scoutResult.reason
                    }
                    const scoutRuns = scoutResult.status === 'fulfilled' ? scoutResult.value : []
                    const signalTasks = signalResult.status === 'fulfilled' ? signalResult.value.results : []
                    // The tab polls every 5s and both endpoints return freshly parsed objects each
                    // time. Reconcile the merged list so a no-change poll keeps every reference —
                    // otherwise all ~100 run cards re-render every 5s on an idle tab. (No
                    // wall-clock exception needed: a run whose status flips deep-compares
                    // different and swaps identity on its own; timestamps self-update in TZLabel.)
                    return reconcileById(
                        values.signalRunsResponse ?? [],
                        mergeSignalRuns(scoutRuns, signalTasks),
                        (run) => run.task_id
                    )
                },
            },
        ],
        // The selected report's base record, loaded by id so detail works regardless of which
        // view/list it came from (and on direct deep-link).
        selectedReportResponse: [
            null as SignalReport | null,
            {
                loadSelectedReport: async ({ id }: { id: string }, breakpoint) => {
                    try {
                        const report = await api.signalReports.get(id)
                        breakpoint()
                        return report
                    } catch (error) {
                        // Discard a superseded load so a slow response for a report the user already
                        // navigated away from can't overwrite the current one (e.g. a stale 404
                        // blanking a valid report that resolved first).
                        breakpoint()
                        // An unresolvable id (a stale deep link, or the onboarding sample card) 404s.
                        // Return null so the scene shows a "not found" empty state instead of the
                        // global raw error toast. Let every other failure surface as before.
                        if (error instanceof ApiError && error.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
            },
        ],
    })),

    reducers({
        selectedReportResponse: {
            // Navigation seeds this directly: the listener resolves the list row (or null) and
            // dispatches `seedSelectedReport` in the same tick, so we never flash through a stale
            // report or a spinner when the row is already loaded. The loader repopulates it on fetch.
            seedSelectedReport: (_, { report }) => report,
        },
        selectedReportId: [
            null as string | null,
            {
                setSelectedReportId: (_, { id }) => id,
            },
        ],
        // Null until a route sets a tab; `activeTab` fills in the layout's landing tab.
        activeTabState: [
            null as InboxTabKey | null,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        selectedScoutSkillName: [
            null as string | null,
            {
                setSelectedScoutSkillName: (_, { skillName }) => skillName,
            },
        ],
        isScratchpadOpen: [
            false,
            {
                setScratchpadOpen: (_, { open }) => open,
                // Opening any other full-width surface closes the memory view.
                setSelectedReportId: (state, { id }) => (id ? false : state),
                setSelectedScoutSkillName: (state, { skillName }) => (skillName ? false : state),
                setFindingsOpen: (state, { open }) => (open ? false : state),
                setRunsOpen: (state, { open }) => (open ? false : state),
                setTriageOpen: (state, { open }) => (open ? false : state),
            },
        ],
        isFindingsOpen: [
            false,
            {
                setFindingsOpen: (_, { open }) => open,
                setSelectedReportId: (state, { id }) => (id ? false : state),
                setSelectedScoutSkillName: (state, { skillName }) => (skillName ? false : state),
                setScratchpadOpen: (state, { open }) => (open ? false : state),
                setRunsOpen: (state, { open }) => (open ? false : state),
                setTriageOpen: (state, { open }) => (open ? false : state),
            },
        ],
        isRunsOpen: [
            false,
            {
                setRunsOpen: (_, { open }) => open,
                setSelectedReportId: (state, { id }) => (id ? false : state),
                setSelectedScoutSkillName: (state, { skillName }) => (skillName ? false : state),
                setScratchpadOpen: (state, { open }) => (open ? false : state),
                setFindingsOpen: (state, { open }) => (open ? false : state),
                setTriageOpen: (state, { open }) => (open ? false : state),
            },
        ],
        isTriageOpen: [
            false,
            {
                setTriageOpen: (_, { open }) => open,
                setSelectedReportId: (state, { id }) => (id ? false : state),
                setSelectedScoutSkillName: (state, { skillName }) => (skillName ? false : state),
                setScratchpadOpen: (state, { open }) => (open ? false : state),
                setFindingsOpen: (state, { open }) => (open ? false : state),
                setRunsOpen: (state, { open }) => (open ? false : state),
            },
        ],
        scoutTemplateDraft: [
            null as ScoutCreateInitialValues | null,
            {
                setScoutTemplateDraft: (_, { draft }) => draft,
            },
        ],
        // The finding deep-linked within the selected scout, if any. Cleared whenever a scout is
        // (re)selected without a finding — navigating to a scout from the fleet drops any prior finding.
        selectedScoutFindingId: [
            null as string | null,
            {
                setSelectedScoutSkillName: (_, { findingId }) => findingId,
            },
        ],
    }),

    selectors({
        isRedesign: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => isInboxRedesignEnabled(featureFlags),
        ],
        // The landing tab differs per layout (Reports under the redesign, Pull requests with the
        // flag off), and a bare `/inbox` keeps whichever tab was already active. A tab set under one
        // layout can outlive a mid-session flag flip (async flag resolution, or a bookmarked URL of
        // the other layout). Fall back to the layout's landing tab when the active tab is not one of
        // this layout's tabs, so the body never renders a tab the active layout has no panel for.
        activeTab: [
            (s) => [s.activeTabState, s.isRedesign],
            (activeTabState: InboxTabKey | null, isRedesign: boolean): InboxTabKey =>
                activeTabState && isInboxTabKey(activeTabState, isRedesign)
                    ? activeTabState
                    : isRedesign
                      ? 'reports'
                      : 'pulls',
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'inbox',
                    name: sceneConfigurations[Scene.Inbox].name,
                    iconType: 'inbox',
                },
            ],
        ],
        isStaff: [
            () => [userLogic.selectors.user],
            (user: null | import('~/types').UserType): boolean => user?.is_staff ?? false,
        ],
        signalRuns: [
            (s) => [s.signalRunsResponse],
            (signalRunsResponse: SignalRun[] | null): SignalRun[] => signalRunsResponse ?? [],
        ],
        // True only while the first load is in flight (response still null), so the Runs panel shows a
        // skeleton instead of the empty state before any data lands. A refetch on re-open keeps the
        // already-loaded list visible rather than flashing the skeleton.
        signalRunsLoading: [
            (s) => [s.signalRunsResponse, s.signalRunsResponseLoading],
            (signalRunsResponse: SignalRun[] | null, signalRunsResponseLoading: boolean): boolean =>
                signalRunsResponse === null && signalRunsResponseLoading,
        ],
        selectedReport: [
            (s) => [s.selectedReportResponse],
            (selectedReportResponse: SignalReport | null): SignalReport | null => selectedReportResponse,
        ],
        selectedReportLoading: [
            (s) => [s.selectedReportResponseLoading],
            (selectedReportResponseLoading: boolean): boolean => selectedReportResponseLoading,
        ],
    }),

    listeners(({ actions, values, cache, selectors }) => ({
        setFeatureFlags: (_, __, ___, previousState) => {
            // Routes handled before PostHog answered ran against the flag the last visit persisted,
            // and held their layout redirects (see `urlToAction`). Route the current URL again once
            // the layout is known, and again on a mid-session flip, so the surface the URL names
            // opens under the layout that renders.
            const wasResolved = featureFlagLogic.selectors.receivedFeatureFlags(previousState)
            if (wasResolved && selectors.isRedesign(previousState) === values.isRedesign) {
                return
            }
            replayInboxLocation()
        },
        setActiveTab: ({ tab }) => {
            // With the flag off the runs list is a tab, so its slow poll follows the tab. Under the
            // redesign it is a panel and `setRunsOpen` owns the poll; it must not be touched here,
            // because opening that panel also moves the tab to Scouts.
            if (values.isRedesign) {
                return
            }
            if (tab === 'runs') {
                actions.loadRuns()
                cache.disposables.add(() => {
                    const interval = setInterval(() => actions.loadRuns(), RUNS_POLL_INTERVAL_MS)
                    return () => clearInterval(interval)
                }, 'runsPoll')
            } else {
                cache.disposables.dispose('runsPoll')
            }
        },
        setRunsOpen: ({ open }) => {
            // While the Runs panel is open, refetch on a slow poll so live runs update in place. The
            // keyed disposable replaces any prior poll and is torn down on close / unmount, and
            // kea-disposables pauses it while the browser tab is hidden. The refetch is silent (the
            // skeleton only shows before the first load), so it swaps the list without flicker.
            if (!open) {
                // The `isRunsOpen` subscription owns poll teardown, so it also catches the closes that
                // flip the panel shut through a mutual-exclusion reducer without dispatching
                // `setRunsOpen(false)` (a report, scout, triage, scratchpad, or findings opening).
                return
            }
            actions.loadRuns()
            cache.disposables.add(() => {
                const interval = setInterval(() => actions.loadRuns(), RUNS_POLL_INTERVAL_MS)
                return () => clearInterval(interval)
            }, 'runsPoll')
            // Close the open report/scout through their own actions so report dwell-time
            // bookkeeping runs (clearing the id in a reducer would skip the close tracking).
            clearScratchpadSearch()
            if (values.selectedReportId !== null) {
                actions.setSelectedReportId(null)
            }
            if (values.selectedScoutSkillName !== null) {
                actions.setSelectedScoutSkillName(null)
            }
            // The runs list is reached from the roster, so its Back control returns to the Scouts tab.
            if (values.activeTab !== 'scouts') {
                actions.setActiveTab('scouts')
            }
        },
        setTriageOpen: ({ open }) => {
            if (!open) {
                return
            }
            clearScratchpadSearch()
            if (values.selectedReportId !== null) {
                actions.setSelectedReportId(null)
            }
            if (values.selectedScoutSkillName !== null) {
                actions.setSelectedScoutSkillName(null)
            }
            // Triage mode triages the Reports tab's queue, so leaving it lands back on Reports.
            if (values.activeTab !== 'reports') {
                actions.setActiveTab('reports')
            }
        },
        setSelectedReportId: ({ id, openMethod }) => {
            // Close the previously open report (if any) before opening/clearing. `next_report` when
            // switching straight to another report, `deselected` when returning to the list.
            const open: InboxOpenTracking | undefined = cache.openTracking
            if (open) {
                const closeMethod: InboxReportCloseMethod = id ? 'next_report' : 'deselected'
                captureInboxReportClosed({
                    report: open.report,
                    timeSpentMs: Date.now() - open.openedAt,
                    closeMethod,
                })
                cache.previousReportId = open.report.id
                cache.openTracking = undefined
            }
            if (!id) {
                actions.seedSelectedReport(null)
                return
            }
            // Opening a report closes the scratchpad (reducer) — clear its transient search so the
            // callout doesn't stay hidden behind a stale no-match filter on the way back.
            clearScratchpadSearch()
            // The open method is resolved once the authoritative record lands in loadSelectedReportSuccess.
            cache.pendingOpenMethod = openMethod
            // A report and a scout detail are mutually exclusive full-width views.
            if (values.selectedScoutSkillName !== null) {
                actions.setSelectedScoutSkillName(null)
            }
            // Under the redesign a report page is a Reports-tab surface even when reached from a
            // scout page, so its back button returns to the report list. With the flag off the
            // report stays under the tab that listed it.
            if (values.isRedesign && values.activeTab !== 'reports') {
                actions.setActiveTab('reports')
            }
            // Reuse the list row if we already have it (instant render), then refresh from the server.
            actions.seedSelectedReport(findLoadedReport(id))
            actions.loadSelectedReport({ id })
        },
        // Fire `Inbox report opened` once the authoritative record lands (skip background refreshes
        // of the already-open report). Rank/list_size come from whichever loaded list holds it.
        loadSelectedReportSuccess: ({ selectedReportResponse }) => {
            const report = selectedReportResponse
            // Skip already-open refreshes, and stale loads for a report the user already navigated away
            // from before the fetch returned (else we'd log a phantom open + a later bogus dwell close).
            if (!report || values.selectedReportId !== report.id || cache.openTracking?.report.id === report.id) {
                return
            }
            const { rank, listSize, section } = findReportRank(report.id)
            captureInboxReportOpened({
                report,
                openMethod: (cache.pendingOpenMethod as InboxReportOpenMethod | undefined) ?? 'unknown',
                previousReportId: cache.previousReportId ?? null,
                rank,
                listSize,
                section,
            })
            cache.openTracking = { report, openedAt: Date.now(), scrolled: false }
            cache.pendingOpenMethod = undefined
            // Best-effort server-side view record: consumption evidence that keeps the authoring
            // scout from being auto-paused as ignored. The analytics event above stays the rich
            // record (rank, open method, dwell), so a failure here is swallowed.
            void signalsReportsViewedCreate(String(teamLogic.values.currentTeamId), report.id).catch(() => {})
        },
        reportDetailScrolled: () => {
            // Fire the dwell signal once per open, on the first scroll. The metric's dwell branch
            // filters `time_since_open_ms >= 5000`, so an immediate scroll is carried but won't qualify.
            const open: InboxOpenTracking | undefined = cache.openTracking
            if (!open || open.scrolled) {
                return
            }
            open.scrolled = true
            const { rank, listSize } = findReportRank(open.report.id)
            captureInboxReportScrolled({
                report: open.report,
                rank,
                listSize,
                timeSinceOpenMs: Date.now() - open.openedAt,
            })
        },
        setSelectedScoutSkillName: ({ skillName }) => {
            if (skillName !== null) {
                // Opening a scout detail closes the scratchpad (reducer) — clear its transient search.
                clearScratchpadSearch()
                if (values.selectedReportId !== null) {
                    actions.setSelectedReportId(null)
                }
                // A scout page is a Scouts-tab surface even when reached from a report or a cold
                // deep link, so anything that closes back to "the tab" returns to the roster. After
                // the report clear, so the tab change resolves to this scout's URL, not the report's.
                if (values.activeTab !== 'scouts') {
                    actions.setActiveTab('scouts')
                }
            }
        },
        setScratchpadOpen: ({ open }) => {
            if (open) {
                // Close the open report/scout through their own actions so report dwell-time
                // bookkeeping runs (clearing the id in a reducer would skip the close tracking).
                if (values.selectedReportId !== null) {
                    actions.setSelectedReportId(null)
                }
                if (values.selectedScoutSkillName !== null) {
                    actions.setSelectedScoutSkillName(null)
                }
                // Same as opening a scout: the panel's Back control returns to the Scouts tab.
                if (values.activeTab !== 'scouts') {
                    actions.setActiveTab('scouts')
                }
            } else {
                clearScratchpadSearch()
            }
        },
        setFindingsOpen: ({ open }) => {
            if (open) {
                // Same dwell-tracking-preserving close as the scratchpad path; clear its transient
                // search so the panel doesn't reopen behind a stale filter on the way back.
                clearScratchpadSearch()
                if (values.selectedReportId !== null) {
                    actions.setSelectedReportId(null)
                }
                if (values.selectedScoutSkillName !== null) {
                    actions.setSelectedScoutSkillName(null)
                }
                if (values.activeTab !== 'scouts') {
                    actions.setActiveTab('scouts')
                }
            }
        },
    })),

    events(({ cache }) => ({
        afterMount: () => {
            // `beforeUnmount` flushes dwell time on in-app navigation, but a tab close or hard page
            // unload never unmounts the scene, so half the closes were dropped. Flush on `pagehide`
            // too. `pauseOnPageHidden: false` keeps the listener alive while the tab is hidden —
            // `pagehide` fires as the tab goes away, exactly when a paused listener would be gone.
            cache.disposables.add(
                () => {
                    const onPageHide = (): void => flushOpenReport(cache, 'page_unload', { send_instantly: true })
                    window.addEventListener('pagehide', onPageHide)
                    return () => window.removeEventListener('pagehide', onPageHide)
                },
                'reportUnloadFlush',
                { pauseOnPageHidden: false }
            )
        },
        // The Runs list loads lazily when its panel opens (via the `setRunsOpen` listener). There is no
        // mount pre-fetch, so an inbox visit that never opens Runs doesn't pay for its two requests.
        beforeUnmount: () => {
            // Flush dwell time for a report still open when the scene unmounts (navigated away).
            flushOpenReport(cache, 'unmount')
        },
    })),

    // The Runs poll (added in the `setRunsOpen` listener) has to stop the moment the panel closes,
    // however it closes. Opening any other full-width surface flips `isRunsOpen` false through a
    // mutual-exclusion reducer rather than dispatching `setRunsOpen(false)`, so this one subscription
    // is the single teardown path that runs for every close — otherwise the poll leaks two requests
    // every 5s for the rest of the visit.
    subscriptions(({ cache }) => ({
        isRunsOpen: (open: boolean) => {
            if (!open) {
                cache.disposables.dispose('runsPoll')
            }
        },
    })),

    actionToUrl(({ values }) => ({
        // Each action resolves to whichever full-width view is left open (or the list), so clearing one
        // because another opened honors that surface's URL rather than bouncing to the list — and a
        // tab change made while a scout surface is open leaves that surface's URL alone.
        setActiveTab: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setSelectedReportId: ({ openMethod }) => [
            inboxSurfaceUrl(values),
            // Opened from triage mode: the report page's back control returns to the spot in the
            // queue, which the triage URL carries at this moment.
            openMethod === 'triage'
                ? { back: removeProjectIdIfPresent(router.values.location.pathname) + router.values.location.search }
                : router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setSelectedScoutSkillName: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setScratchpadOpen: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setFindingsOpen: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setRunsOpen: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setTriageOpen: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
    })),

    urlToAction(({ actions, values, cache }) => {
        const closeAllSurfaces = (): void => {
            if (values.selectedReportId !== null) {
                actions.setSelectedReportId(null)
            }
            if (values.selectedScoutSkillName !== null) {
                actions.setSelectedScoutSkillName(null)
            }
            if (values.isScratchpadOpen) {
                actions.setScratchpadOpen(false)
            }
            if (values.isFindingsOpen) {
                actions.setFindingsOpen(false)
            }
            if (values.isRunsOpen) {
                actions.setRunsOpen(false)
            }
            if (values.isTriageOpen) {
                actions.setTriageOpen(false)
            }
        }
        // A layout redirect rewrites the URL for the layout the flag names. On a cold load the
        // handlers run before PostHog answers, against the flag the last visit persisted, and a
        // redirect issued then would erase the surface the URL names before the `setFeatureFlags`
        // listener can route it again. Hold the URL until flags land; that listener replays it.
        const redirectForLayout = (
            path: string,
            searchParams: Record<string, any>,
            hashParams: Record<string, any>
        ): boolean => {
            if (!values.receivedFeatureFlags) {
                return false
            }
            router.actions.replace(path, searchParams, hashParams)
            return true
        }
        return {
            [urls.inboxScratchpad()]: () => {
                if (!values.isScratchpadOpen) {
                    actions.setScratchpadOpen(true)
                }
            },
            [urls.inboxFindings()]: () => {
                if (!values.isFindingsOpen) {
                    actions.setFindingsOpen(true)
                }
            },
            [urls.inboxRuns()]: (_, searchParams, hashParams) => {
                // With the flag off the runs list is still the Runs tab.
                if (!values.isRedesign) {
                    redirectForLayout(urls.inbox('runs'), searchParams, hashParams)
                    return
                }
                if (!values.isRunsOpen) {
                    actions.setRunsOpen(true)
                }
            },
            [urls.inboxTriage()]: (_, searchParams, hashParams) => {
                // Triage mode only exists under the redesign; the queue it walks is the Reports tab.
                if (!values.isRedesign) {
                    redirectForLayout(urls.inbox('reports'), searchParams, hashParams)
                    return
                }
                cache.inboxListVisited = true
                if (!values.isTriageOpen) {
                    actions.setTriageOpen(true)
                }
            },
            [urls.inbox()]: (_, __, hashParams) => {
                cache.inboxListVisited = true
                consumeScoutTemplateHash(actions, hashParams)
                closeAllSurfaces()
            },
            [urls.inbox(':tab')]: ({ tab }: { tab?: string }, searchParams, hashParams) => {
                // Tab segments from the other inbox layout still arrive from Slack messages, bookmarks,
                // and a flag that flipped between visits: send them to the surface that replaced them.
                const redirectPath = inboxTabRedirectPath(tab, values.isRedesign)
                if (redirectPath) {
                    redirectForLayout(redirectPath, searchParams, hashParams)
                    return
                }
                // A bare report deep-link `/inbox/<reportId>` is redirected to report form. Mark the list
                // as visited only when we're actually staying on a list view — otherwise the redirected
                // report would be misclassified as an in-app click instead of a deep-link.
                if (tab && !isInboxTabKey(tab, values.isRedesign)) {
                    router.actions.replace(urls.inboxReport('reports', tab), searchParams, hashParams)
                    return
                }
                cache.inboxListVisited = true
                consumeScoutTemplateHash(actions, hashParams)
                // Staff-only tabs (Not actionable): bounce non-staff to the default tab. Under the
                // redesign that list is a section the Reports tab hides from non-staff instead.
                if (!values.isRedesign && isStaffOnlyTab(tab) && userLogic.values.user != null && !values.isStaff) {
                    actions.setActiveTab('pulls')
                    return
                }
                if (isInboxTabKey(tab, values.isRedesign) && values.activeTab !== tab) {
                    actions.setActiveTab(tab)
                }
                closeAllSurfaces()
            },
            [urls.inboxScout(':skillName')]: ({ skillName }: { skillName?: string }) => {
                // `/inbox/scouts/scratchpad`, `/inbox/scouts/findings`, and `/inbox/scouts/runs` also match
                // this pattern; their own handlers own those paths (no real scout skill_name collides —
                // they're `signals-scout-*`).
                if (skillName === 'scratchpad' || skillName === 'findings' || skillName === 'runs') {
                    return
                }
                const name = skillName ?? null
                // Also reset the finding when landing on the bare scout URL after a finding deep-link.
                if (values.selectedScoutSkillName !== name || values.selectedScoutFindingId !== null) {
                    actions.setSelectedScoutSkillName(name)
                }
            },
            [urls.inboxScout(':skillName', ':findingId')]: ({
                skillName,
                findingId,
            }: {
                skillName?: string
                findingId?: string
            }) => {
                const name = skillName ?? null
                const finding = findingId ?? null
                if (values.selectedScoutSkillName !== name || values.selectedScoutFindingId !== finding) {
                    actions.setSelectedScoutSkillName(name, finding)
                }
            },
            [urls.inboxReport(':tab', ':reportId')]: (
                { tab, reportId }: { tab?: string; reportId?: string },
                searchParams,
                hashParams
            ) => {
                // This pattern also matches `/inbox/scouts/<skillName>` and `/inbox/reports/triage`;
                // their own handlers own those paths.
                if (tab === 'scouts' || (tab === 'reports' && reportId === 'triage')) {
                    return
                }
                if (!reportId) {
                    return
                }
                if (values.isRedesign) {
                    // `/inbox/pulls/<id>` and friends: the same report, now addressed through the one
                    // Reports list that replaced those tabs. While the redirect is held, open the
                    // report under this layout rather than leave the page empty until flags land.
                    if (
                        tab !== 'reports' &&
                        redirectForLayout(urls.inboxReport('reports', reportId), searchParams, hashParams)
                    ) {
                        return
                    }
                    if (values.activeTab !== 'reports') {
                        actions.setActiveTab('reports')
                    }
                } else {
                    if (isStaffOnlyTab(tab) && userLogic.values.user != null && !values.isStaff) {
                        actions.setActiveTab('pulls')
                        return
                    }
                    if (isInboxTabKey(tab, false) && values.activeTab !== tab) {
                        actions.setActiveTab(tab)
                    }
                }
                if (values.selectedReportId !== reportId) {
                    // A `back` pointing at triage means the open came from the triage card's "Full
                    // report" link, which navigates by URL rather than through `openCurrent`; attribute
                    // it to triage so the metric isn't split with plain list clicks. Otherwise: a first
                    // route before any list URL was seen is a cold deep-link, else an in-app click.
                    const fromTriage =
                        typeof searchParams.back === 'string' && searchParams.back.startsWith(urls.inboxTriage())
                    actions.setSelectedReportId(
                        reportId,
                        fromTriage ? 'triage' : cache.inboxListVisited ? 'click' : 'deeplink'
                    )
                }
            },
        }
    }),
])
