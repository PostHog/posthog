import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { captureInboxOnboardingDecided } from '../inboxAnalytics'
import { signalSourcesLogic } from '../signalSourcesLogic'
import { type SignalSourceConfig } from '../types'
import { inboxSetupLogic } from './inboxSetupLogic'
import { INBOX_REPORT_SECTION_LIST_PARAMS, reportListLogic } from './reportListLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

// Throttle for the return-to-tab refetch. The disposables plugin re-runs setup on every
// `visibilitychange → visible`; without a floor, alt-tab flapping turns into request bursts.
const VISIBILITY_REFETCH_THROTTLE_MS = 5 * 1000

/** How the self-driving onboarding presents itself over the inbox. */
export type InboxOnboardingMode = 'takeover' | 'banner' | 'none' | 'pending'

/** What the inbox rendered last time the verdict settled: the welcome takeover, or the normal
 * inbox (with or without the banner). Cached per team so the next visit shows it instantly. */
export type InboxSettledUiState = 'takeover' | 'inbox'

/** localStorage key for the per-team last-settled UI state (see `lastSettledUiStateByTeam`). */
// pinned: browser storage key - a rename orphans what every user already stored, so the inbox
// forgets which UI it painted last visit and falls back to the skeleton on their next one.
export const INBOX_LAST_UI_STATE_STORAGE_KEY = 'inbox-onboarding-last-ui-state'

/**
 * Why the onboarding is not showing. `null` whenever it is.
 */
export type InboxOnboardingSuppressionReason =
    | 'setup_loading'
    | 'already_set_up'
    | 'counts_loading'
    | 'refetching'
    | 'banner_dismissed'
    | null

export interface InboxOnboardingDecision {
    mode: InboxOnboardingMode
    reason: InboxOnboardingSuppressionReason
}

export interface OnboardingModeInputs {
    /** Every watcher loader has settled, so the set-up verdict is trustworthy. */
    isSetupLoaded: boolean
    /** At least one signal source, scout, or signal-emitting Replay Vision scanner is watching. */
    isSelfDrivingSetUp: boolean
    /** Both tab count loaders have settled (returned, or failed) – the work verdict is trustworthy. */
    areCountsResolved: boolean
    /** There are existing reports or PRs in the inbox. */
    hasExistingWork: boolean
    /** The banner was dismissed this session. */
    bannerDismissed: boolean
    /** A config/count refetch is in flight, so the loaded values may be about to change (e.g. the
     * user returned to the tab). */
    isRefetching: boolean
}

/**
 * Pure decision for how (if at all) the onboarding shows.
 *
 * While the takeover is still on the table but the inputs haven't settled, the verdict is
 * `'pending'`: the scene renders a neutral skeleton with no tab bar, so the user never sees the
 * normal inbox flash in and get replaced by the welcome takeover (or vice versa). As soon as any
 * settled input rules the takeover out – self-driving is set up, or work already exists (the banner is additive, not a replacement) – the normal inbox shows
 * immediately without waiting on the rest.
 *
 * Each outcome carries the input it is waiting on (or the reason it is withheld), so telemetry can
 * tell a prompt nobody needed from one that never resolved.
 */
export function computeOnboardingDecision({
    isSetupLoaded,
    isSelfDrivingSetUp,
    areCountsResolved,
    hasExistingWork,
    bannerDismissed,
    isRefetching,
}: OnboardingModeInputs): InboxOnboardingDecision {
    // Set-up users go straight to their inbox the moment the config check lands – the report
    // counts could not flip their verdict to an onboarding.
    if (isSetupLoaded && isSelfDrivingSetUp) {
        return { mode: 'none', reason: 'already_set_up' }
    }
    // Work already in the inbox rules the takeover out: the only remaining outcomes (banner /
    // none) both render the normal inbox, so show it now rather than holding a skeleton. The
    // non-blocking banner joins once the config check settles.
    if (areCountsResolved && hasExistingWork) {
        if (!isSetupLoaded) {
            return { mode: 'none', reason: 'setup_loading' }
        }
        return bannerDismissed ? { mode: 'none', reason: 'banner_dismissed' } : { mode: 'banner', reason: null }
    }
    // The takeover is still possible. Until every input has settled – configs (is anything
    // watching?) and counts (is there work to keep?) – committing to either UI risks flashing it
    // and swapping it out, so hold the neutral skeleton. A refetch in flight means the loaded values
    // may be stale in the same way (the user returned to the tab), so it holds the takeover back too.
    if (!isSetupLoaded) {
        return { mode: 'pending', reason: 'setup_loading' }
    }
    if (!areCountsResolved) {
        return { mode: 'pending', reason: 'counts_loading' }
    }
    if (isRefetching) {
        return { mode: 'pending', reason: 'refetching' }
    }
    return { mode: 'takeover', reason: null }
}

/**
 * What the inbox should render right now: the resolved verdict once it has settled, else the UI
 * the same team saw last time (the verdict is almost always the same visit to visit, and if it
 * isn't, the state genuinely changed and a swap is honest). The neutral skeleton is left only
 * for a team's very first visit, when there's no history to lean on.
 */
export function resolveDisplayMode(
    resolvedMode: InboxOnboardingMode,
    lastSettledUiState: InboxSettledUiState | null
): InboxOnboardingMode {
    if (resolvedMode !== 'pending') {
        return resolvedMode
    }
    if (lastSettledUiState === 'takeover') {
        return 'takeover'
    }
    if (lastSettledUiState === 'inbox') {
        return 'none'
    }
    return 'pending'
}

/**
 * A background-managed scout or an operational scout is not set up: nobody on the project turned
 * it on. The first inbox visit seeds the operational scouts enabled, so counting them would skip
 * onboarding for every project that only has the background scout.
 */
export function computeIsSelfDrivingSetUp(
    enabledSourcesCount: number,
    scoutConfigs: Pick<SignalScoutConfig, 'enabled' | 'managed_by' | 'scout_role'>[] | null
): boolean {
    return (
        enabledSourcesCount > 0 ||
        !!scoutConfigs?.some(
            (config) => config.enabled && config.managed_by !== 'background' && config.scout_role !== 'operational'
        )
    )
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxOnboardingLogicValues {
    setupCompleted: boolean // inboxSetupLogic
    setupInProgress: boolean // inboxSetupLogic
    setupStateLoading: boolean // inboxSetupLogic
    pullsCount: number | null // reportListLogic
    pullsCountLoading: boolean // reportListLogic
    reportsCount: number | null // reportListLogic
    reportsCountLoading: boolean // reportListLogic
    searchParams: Record<string, any> // router
    scoutConfigs: SignalScoutConfig[] | null // scoutFleetLogic
    scoutConfigsLoading: boolean // scoutFleetLogic
    enabledSourcesCount: number // signalSourcesLogic
    hasEmittingScanner: boolean | null // signalSourcesLogic
    sourceConfigs: SignalSourceConfig[] | null // signalSourcesLogic
    sourceConfigsLoading: boolean // signalSourcesLogic
    currentTeamId: number | null // teamLogic
    areCountsResolved: boolean
    bannerDismissed: boolean
    hasExistingWork: boolean
    isRefetching: boolean
    isSelfDrivingSetUp: boolean
    isSetupLoaded: boolean
    lastSettledUiState: InboxSettledUiState | null
    lastSettledUiStateByTeam: Record<string, InboxSettledUiState>
    onboardingDecision: InboxOnboardingDecision
    onboardingMode: InboxOnboardingMode
    resolvedOnboardingMode: InboxOnboardingMode
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxOnboardingLogicActions {
    loadPullsCount: (_?: void | undefined) => void // reportListLogic
    loadReportsCount: (_?: void | undefined) => void // reportListLogic
    loadScoutConfigs: (_?: void | undefined) => void // scoutFleetLogic
    loadSourceConfigs: () => any // signalSourcesLogic
    dismissBanner: () => {
        value: true
    }
    refreshSetupState: () => {
        value: true
    }
    setLastSettledUiState: (
        teamId: number,
        uiState: InboxSettledUiState
    ) => {
        teamId: number
        uiState: InboxSettledUiState
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxOnboardingLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        isSelfDrivingSetUp: (enabledSourcesCount: number, scoutConfigs: SignalScoutConfig[] | null) => boolean
        isSetupLoaded: (
            sourceConfigs: SignalSourceConfig[] | null,
            scoutConfigs: SignalScoutConfig[] | null,
            hasEmittingScanner: boolean | null
        ) => boolean
        areCountsResolved: (
            pullsCount: number | null,
            reportsCount: number | null,
            pullsCountLoading: boolean,
            reportsCountLoading: boolean
        ) => boolean
        hasExistingWork: (pullsCount: number | null, reportsCount: number | null) => boolean
        isRefetching: (
            sourceConfigsLoading: boolean,
            scoutConfigsLoading: boolean,
            pullsCountLoading: boolean,
            reportsCountLoading: boolean
        ) => boolean
        onboardingDecision: (
            isSetupLoaded: boolean,
            isSelfDrivingSetUp: boolean,
            areCountsResolved: boolean,
            hasExistingWork: boolean,
            bannerDismissed: boolean,
            isRefetching: boolean
        ) => InboxOnboardingDecision
        resolvedOnboardingMode: (onboardingDecision: InboxOnboardingDecision) => InboxOnboardingMode
        lastSettledUiState: (
            lastSettledUiStateByTeam: Record<string, InboxSettledUiState>,
            currentTeamId: number | null
        ) => InboxSettledUiState | null
        onboardingMode: (
            resolvedOnboardingMode: InboxOnboardingMode,
            lastSettledUiState: InboxSettledUiState | null,
            searchParams: Record<string, any>,
            isSelfDrivingSetUp: boolean,
            setupInProgress: boolean,
            setupCompleted: boolean,
            setupStateLoading: boolean
        ) => InboxOnboardingMode
    }
}

export type inboxOnboardingLogicType = MakeLogicType<
    inboxOnboardingLogicValues,
    inboxOnboardingLogicActions,
    Record<string, any>,
    inboxOnboardingLogicMeta
>

/**
 * Decides how the self-driving onboarding presents itself. A project that completed the in-app
 * setup goes straight to its inbox, and one that is mid-setup keeps the takeover. For every other
 * project, "set up" is read from what ends up watching: at least one signal source or scout.
 * `enabledSourcesCount` counts Replay Vision too, which reaches the inbox on its own.
 *
 * When self-driving is NOT set up, the presentation depends on whether there's anything to show:
 * - nothing landed yet (no reports or PRs) → the inbox becomes a locked "Welcome" tab whose body is
 *   the onboarding card (the other tabs are visible but disabled). Nothing to block, so we lean in.
 * - reports or PRs already exist (they had sources/scouts before) → a sleek, non-blocking banner
 *   above the inbox, so the team keeps access to their work while we entice them to re-enable.
 *
 * The banner is session-dismissable; it returns next time the inbox is opened still un-set-up.
 * The takeover has no dismiss – there's nothing behind it to reach.
 */
export const inboxOnboardingLogic = kea<inboxOnboardingLogicType>([
    path(['scenes', 'inbox', 'logics', 'inboxOnboardingLogic']),

    connect(() => ({
        values: [
            inboxSetupLogic,
            ['inProgress as setupInProgress', 'completed as setupCompleted', 'savedStateLoading as setupStateLoading'],
            signalSourcesLogic,
            ['sourceConfigs', 'sourceConfigsLoading', 'enabledSourcesCount', 'hasEmittingScanner'],
            scoutFleetLogic,
            ['scoutConfigs', 'scoutConfigsLoading'],
            // Mount the monitoring + needs-decision count loaders directly (cheap limit=1 each) so we
            // know whether there's existing work even during a takeover, when the view switcher that
            // usually mounts these isn't rendered. Same keyed instances it uses – no double-fetch.
            reportListLogic({ sectionKey: 'monitoring', listParams: INBOX_REPORT_SECTION_LIST_PARAMS.monitoring }),
            ['count as pullsCount', 'countLoading as pullsCountLoading'],
            reportListLogic({
                sectionKey: 'needs-decision',
                listParams: INBOX_REPORT_SECTION_LIST_PARAMS['needs-decision'],
            }),
            ['count as reportsCount', 'countLoading as reportsCountLoading'],
            teamLogic,
            ['currentTeamId'],
            router,
            ['searchParams'],
        ],
        actions: [
            signalSourcesLogic,
            ['loadSourceConfigs'],
            scoutFleetLogic,
            ['loadScoutConfigs'],
            reportListLogic({ sectionKey: 'monitoring', listParams: INBOX_REPORT_SECTION_LIST_PARAMS.monitoring }),
            ['loadCount as loadPullsCount'],
            reportListLogic({
                sectionKey: 'needs-decision',
                listParams: INBOX_REPORT_SECTION_LIST_PARAMS['needs-decision'],
            }),
            ['loadCount as loadReportsCount'],
        ],
    })),

    actions({
        dismissBanner: true,
        setLastSettledUiState: (teamId: number, uiState: InboxSettledUiState) => ({ teamId, uiState }),
        refreshSetupState: true,
    }),

    listeners(({ actions }) => ({
        // Re-pull everything the verdict is computed from. Fired when the user returns to a tab whose
        // verdict still says "not set up".
        refreshSetupState: () => {
            actions.loadSourceConfigs()
            actions.loadScoutConfigs()
            actions.loadPullsCount()
            actions.loadReportsCount()
        },
    })),

    reducers({
        bannerDismissed: [
            false,
            {
                dismissBanner: () => true,
            },
        ],
        // Keyed by team: the verdict is per team, and a cached verdict from another team must not
        // leak into this one's first paint after a project switch.
        lastSettledUiStateByTeam: [
            {} as Record<string, InboxSettledUiState>,
            { persist: true, storageKey: INBOX_LAST_UI_STATE_STORAGE_KEY },
            {
                setLastSettledUiState: (state, { teamId, uiState }) =>
                    state[teamId] === uiState ? state : { ...state, [teamId]: uiState },
            },
        ],
    }),

    selectors({
        isSelfDrivingSetUp: [
            (s) => [s.enabledSourcesCount, s.scoutConfigs],
            (enabledSourcesCount: number, scoutConfigs: SignalScoutConfig[] | null): boolean =>
                computeIsSelfDrivingSetUp(enabledSourcesCount, scoutConfigs),
        ],
        // Every watcher loader has settled, so the set-up verdict is trustworthy.
        isSetupLoaded: [
            (s) => [s.sourceConfigs, s.scoutConfigs, s.hasEmittingScanner],
            (
                sourceConfigs: import('../types').SignalSourceConfig[] | null,
                scoutConfigs: SignalScoutConfig[] | null,
                hasEmittingScanner: boolean | null
            ): boolean => sourceConfigs !== null && scoutConfigs !== null && hasEmittingScanner !== null,
        ],
        // Counts are "resolved" once both limit=1 requests have returned, OR once neither is still
        // loading (so a failed count request can't strand the onboarding on the loading state – this
        // is only consulted after the configs have loaded, by which point the counts have started).
        areCountsResolved: [
            (s) => [s.pullsCount, s.reportsCount, s.pullsCountLoading, s.reportsCountLoading],
            (
                pullsCount: number | null,
                reportsCount: number | null,
                pullsCountLoading: boolean,
                reportsCountLoading: boolean
            ): boolean =>
                (pullsCount !== null && reportsCount !== null) || (!pullsCountLoading && !reportsCountLoading),
        ],
        hasExistingWork: [
            (s) => [s.pullsCount, s.reportsCount],
            (pullsCount: number | null, reportsCount: number | null): boolean =>
                (pullsCount ?? 0) + (reportsCount ?? 0) > 0,
        ],
        // A config or count request is in flight. While true, the verdict must not commit to the
        // takeover: the loaded values are about to change.
        isRefetching: [
            (s) => [s.sourceConfigsLoading, s.scoutConfigsLoading, s.pullsCountLoading, s.reportsCountLoading],
            (
                sourceConfigsLoading: boolean,
                scoutConfigsLoading: boolean,
                pullsCountLoading: boolean,
                reportsCountLoading: boolean
            ): boolean => sourceConfigsLoading || scoutConfigsLoading || pullsCountLoading || reportsCountLoading,
        ],
        // The verdict from live inputs alone, with the input it is still waiting on. Kept separate
        // from `onboardingMode` so neither the cache writer nor the telemetry below ever reports a
        // guess that itself came from the cache.
        onboardingDecision: [
            (s) => [
                s.isSetupLoaded,
                s.isSelfDrivingSetUp,
                s.areCountsResolved,
                s.hasExistingWork,
                s.bannerDismissed,
                s.isRefetching,
            ],
            (
                isSetupLoaded: boolean,
                isSelfDrivingSetUp: boolean,
                areCountsResolved: boolean,
                hasExistingWork: boolean,
                bannerDismissed: boolean,
                isRefetching: boolean
            ): InboxOnboardingDecision =>
                computeOnboardingDecision({
                    isSetupLoaded,
                    isSelfDrivingSetUp,
                    areCountsResolved,
                    hasExistingWork,
                    bannerDismissed,
                    isRefetching,
                }),
        ],
        resolvedOnboardingMode: [
            (s) => [s.onboardingDecision],
            (onboardingDecision: InboxOnboardingDecision): InboxOnboardingMode => onboardingDecision.mode,
        ],
        lastSettledUiState: [
            (s) => [s.lastSettledUiStateByTeam, s.currentTeamId],
            (
                lastSettledUiStateByTeam: Record<string, InboxSettledUiState>,
                currentTeamId: number | null
            ): InboxSettledUiState | null =>
                currentTeamId != null ? (lastSettledUiStateByTeam[currentTeamId] ?? null) : null,
        ],
        // What the scene renders: while the verdict is settling, fall back to what this team saw
        // last visit instead of a skeleton, so the loading state only ever shows on a first visit.
        onboardingMode: [
            (s) => [
                s.resolvedOnboardingMode,
                s.lastSettledUiState,
                s.searchParams,
                s.isSelfDrivingSetUp,
                s.setupInProgress,
                s.setupCompleted,
                s.setupStateLoading,
            ],
            (
                resolvedOnboardingMode: InboxOnboardingMode,
                lastSettledUiState: InboxSettledUiState | null,
                searchParams: Record<string, unknown>,
                isSelfDrivingSetUp: boolean,
                setupInProgress: boolean,
                setupCompleted: boolean,
                setupStateLoading: boolean
            ): InboxOnboardingMode => {
                if (setupCompleted) {
                    return 'none'
                }
                if (setupInProgress) {
                    return 'takeover'
                }
                if (setupStateLoading) {
                    return 'pending'
                }
                if (searchParams.setup === 'github-first' && !isSelfDrivingSetUp) {
                    return 'takeover'
                }
                return resolveDisplayMode(resolvedOnboardingMode, lastSettledUiState)
            },
        ],
    }),

    subscriptions(({ actions, values, cache }) => ({
        // One event per distinct verdict per mount. The decision settles through several
        // intermediate holds as its inputs load, so reporting every transition would drown the
        // real answer; deduping on the pair keeps the loading states as the trail that explains it.
        onboardingDecision: (decision: InboxOnboardingDecision) => {
            const key = `${decision.mode}:${decision.reason ?? 'shown'}`
            if (cache.reportedDecisions?.has(key)) {
                return
            }
            cache.reportedDecisions = (cache.reportedDecisions ?? new Set<string>()).add(key)
            captureInboxOnboardingDecided({ mode: decision.mode, reason: decision.reason })
        },
        // Remember what this team's verdict rendered as, so the next visit can paint it
        // immediately while the checks re-run. Watches the resolved mode (not the display mode)
        // so the cache is only ever written from settled inputs.
        resolvedOnboardingMode: (resolvedMode: InboxOnboardingMode) => {
            const teamId = values.currentTeamId
            if (resolvedMode === 'pending' || teamId == null) {
                return
            }
            actions.setLastSettledUiState(teamId, resolvedMode === 'takeover' ? 'takeover' : 'inbox')
        },
    })),

    afterMount(({ actions, values, cache }) => {
        // Refetch on return to the tab, but only while the verdict still says "not set up": that
        // is the copy-the-command flow (terminal → wizard → back to this tab), where the configs
        // and counts loaded at mount are exactly the stale ones. Set-up users are excluded, so an
        // inbox parked in a background tab doesn't re-pull four endpoints on every focus. The
        // setup re-runs on every `visibilitychange → visible`; the first run at mount is skipped
        // (the loaders fetch on their own mount) and alt-tab flapping is throttled.
        cache.disposables.add(() => {
            if (!cache.visibilityRefetchArmed) {
                cache.visibilityRefetchArmed = true
                return () => {}
            }
            const now = Date.now()
            const throttled = now - (cache.lastVisibilityRefetch ?? 0) < VISIBILITY_REFETCH_THROTTLE_MS
            if (!throttled && !(values.isSetupLoaded && values.isSelfDrivingSetUp)) {
                cache.lastVisibilityRefetch = now
                actions.refreshSetupState()
            }
            return () => {}
        }, 'refetch-on-return')
    }),
])
