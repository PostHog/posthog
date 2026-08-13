import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { captureInboxOnboardingDecided } from '../inboxAnalytics'
import { signalSourcesLogic } from '../signalSourcesLogic'
import type { SignalSourceConfig } from '../types'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from './reportListLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

// Spread for the mount-time wizard check. Short enough that a user arriving from onboarding gets
// their verdict almost immediately, long enough that a fleet-wide reload doesn't land as one spike.
const MOUNT_CHECK_JITTER_MS = 3 * 1000

// Throttle for the return-to-tab refetch. The disposables plugin re-runs setup on every
// `visibilitychange → visible`; without a floor, alt-tab flapping turns into request bursts.
const VISIBILITY_REFETCH_THROTTLE_MS = 5 * 1000

// Ceiling on how long the wizard verdict may hold the prompt back. The verdict can never arrive:
// the shortcut below needs the feature-flag payload, which an ad blocker can drop entirely, and a
// detector whose endpoint keeps erroring only settles after enough consecutive failures. Both leave
// someone who has not set self-driving up on an inbox that never offers to. Well past the sub-second
// window the guard exists for (jitter plus one request), so capping it costs the normal path nothing.
const WIZARD_VERDICT_DEADLINE_MS = 15 * 1000

/** How the self-driving onboarding presents itself over the inbox. */
export type InboxOnboardingMode = 'takeover' | 'banner' | 'none' | 'pending'

/** What the inbox rendered last time the verdict settled: the welcome takeover, or the normal
 * inbox (with or without the banner). Cached per team so the next visit shows it instantly. */
export type InboxSettledUiState = 'takeover' | 'inbox'

/** localStorage key for the per-team last-settled UI state (see `lastSettledUiStateByTeam`). */
export const INBOX_LAST_UI_STATE_STORAGE_KEY = 'inbox-onboarding-last-ui-state'

/**
 * Why the onboarding is not showing. `null` whenever it is.
 *
 * `'wizard_running'` is the only deliberate suppression; every other value is an input the decision
 * is still waiting on, or a user who does not need onboarding at all. Carried into telemetry so a
 * withheld prompt is distinguishable from an absent one.
 */
export type InboxOnboardingSuppressionReason =
    | 'wizard_running'
    | 'wizard_state_unknown'
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

export interface WizardStateInputs {
    /** The detector reached a verdict: a poll settled, a stream reported in, or polling was killed. */
    hasResolvedSessionState: boolean
    /** Programs the detector polls. Derived from the onboarding variant, so it needs flags in hand. */
    watchedWorkflows: string[]
    receivedFeatureFlags: boolean
    /** The deadline above elapsed with no verdict, so waiting longer only withholds the prompt. */
    verdictWaitExpired: boolean
}

/**
 * Whether `isWizardRunning === false` can be acted on.
 *
 * Trivially true when the detector isn't watching the self-driving program (control variant, no
 * surface registered): its verdict could never flip `isWizardRunning`, so waiting on it — or polling
 * eagerly for it — would cost every inbox user something for nothing. That shortcut needs flags in
 * hand though: `watchedWorkflows` is derived from the onboarding variant, and before the flags land
 * it reads as the control arm for everyone, which would let the takeover render for a user whose run
 * is mid-flight and then flicker back out once the flags arrive.
 *
 * The deadline is the backstop for the case where neither of those ever resolves. A takeover that
 * flickers is a worse first second than one that waits; a takeover that never renders is worse than
 * both, and it is the only failure of the three a user can't recover from by waiting.
 */
export function resolveWizardState({
    hasResolvedSessionState,
    watchedWorkflows,
    receivedFeatureFlags,
    verdictWaitExpired,
}: WizardStateInputs): boolean {
    return (
        hasResolvedSessionState ||
        (receivedFeatureFlags && !watchedWorkflows.includes(SELF_DRIVING_WORKFLOW_ID)) ||
        verdictWaitExpired
    )
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
    /** A self-driving wizard run is in flight, so setup is already under way elsewhere. */
    isWizardRunning: boolean
    /** The wizard detector has actually checked, so `isWizardRunning === false` is a verdict rather
     * than "nobody asked yet". */
    isWizardStateResolved: boolean
    /** A config/count refetch is in flight, so the loaded values may be about to change (e.g. the
     * wizard just finished, or the user returned to the tab). */
    isRefetching: boolean
}

/**
 * Pure decision for how (if at all) the onboarding shows.
 *
 * While the takeover is still on the table but the inputs haven't settled, the verdict is
 * `'pending'`: the scene renders a neutral skeleton with no tab bar, so the user never sees the
 * normal inbox flash in and get replaced by the welcome takeover (or vice versa). As soon as any
 * settled input rules the takeover out – self-driving is set up, a wizard run is in flight, or
 * work already exists (the banner is additive, not a replacement) – the normal inbox shows
 * immediately without waiting on the rest.
 *
 * Each outcome carries the input it is waiting on (or the reason it is withheld), so telemetry can
 * tell a prompt nobody needed from one that never resolved. `resolveWizardState` bounds the one
 * wait that can hang forever.
 */
export function computeOnboardingDecision({
    isSetupLoaded,
    isSelfDrivingSetUp,
    areCountsResolved,
    hasExistingWork,
    bannerDismissed,
    isWizardRunning,
    isWizardStateResolved,
    isRefetching,
}: OnboardingModeInputs): InboxOnboardingDecision {
    // A run in flight is setup in progress: sources and scouts land as it goes, so telling the user
    // to go and run the wizard would contradict the progress widget already showing it running.
    if (isWizardRunning) {
        return { mode: 'none', reason: 'wizard_running' }
    }
    // Set-up users go straight to their inbox the moment the config check lands – neither the
    // wizard detector nor the report counts could flip their verdict to an onboarding.
    if (isSetupLoaded && isSelfDrivingSetUp) {
        return { mode: 'none', reason: 'already_set_up' }
    }
    // Work already in the inbox rules the takeover out: the only remaining outcomes (banner /
    // none) both render the normal inbox, so show it now rather than holding a skeleton. The
    // non-blocking banner joins once the config and wizard checks settle.
    if (areCountsResolved && hasExistingWork) {
        if (!isSetupLoaded) {
            return { mode: 'none', reason: 'setup_loading' }
        }
        if (!isWizardStateResolved) {
            return { mode: 'none', reason: 'wizard_state_unknown' }
        }
        return bannerDismissed ? { mode: 'none', reason: 'banner_dismissed' } : { mode: 'banner', reason: null }
    }
    // The takeover is still possible. Until every input has settled – configs (is anything
    // watching?), counts (is there work to keep?), and the wizard detector (is a run in flight?) –
    // committing to either UI risks flashing it and swapping it out, so hold the neutral skeleton.
    // A refetch in flight means the loaded values may be stale in the same way (the wizard just
    // finished, or the user returned to the tab), so it holds the takeover back too.
    if (!isSetupLoaded) {
        return { mode: 'pending', reason: 'setup_loading' }
    }
    if (!isWizardStateResolved) {
        return { mode: 'pending', reason: 'wizard_state_unknown' }
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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxOnboardingLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    receivedFeatureFlags: boolean // featureFlagLogic
    pullsCount: number | null // reportListLogic
    pullsCountLoading: boolean // reportListLogic
    reportsCount: number | null // reportListLogic
    reportsCountLoading: boolean // reportListLogic
    enabledScoutsCount: number // scoutFleetLogic
    scoutConfigs: SignalScoutConfig[] | null // scoutFleetLogic
    scoutConfigsLoading: boolean // scoutFleetLogic
    enabledSourcesCount: number // signalSourcesLogic
    hasEmittingScanner: boolean | null // signalSourcesLogic
    sourceConfigs: SignalSourceConfig[] | null // signalSourcesLogic
    sourceConfigsLoading: boolean // signalSourcesLogic
    currentTeamId: number | null // teamLogic
    activeWorkflowId: string | null // wizardActiveSessionDetectorLogic
    hasResolvedSessionState: boolean // wizardActiveSessionDetectorLogic
    watchedWorkflows: string[] // wizardActiveSessionDetectorLogic
    areCountsResolved: boolean
    bannerDismissed: boolean
    hasExistingWork: boolean
    isRefetching: boolean
    isSelfDrivingSetUp: boolean
    isSetupLoaded: boolean
    isWelcomeRedesign: boolean
    isWizardRunning: boolean
    isWizardStateResolved: boolean
    lastSettledUiState: InboxSettledUiState | null
    lastSettledUiStateByTeam: Record<string, InboxSettledUiState>
    onboardingDecision: InboxOnboardingDecision
    onboardingMode: InboxOnboardingMode
    resolvedOnboardingMode: InboxOnboardingMode
    verdictWaitExpired: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxOnboardingLogicActions {
    loadPullsCount: () => any // reportListLogic
    loadReportsCount: () => any // reportListLogic
    loadScoutConfigs: () => any // scoutFleetLogic
    loadSourceConfigs: () => any // signalSourcesLogic
    checkWizardSession: () => {
        value: true
    } // wizardActiveSessionDetectorLogic
    dismissBanner: () => {
        value: true
    }
    expireWizardVerdictWait: () => {
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
        isSelfDrivingSetUp: (enabledSourcesCount: number, enabledScoutsCount: number) => boolean
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
        isWizardRunning: (activeWorkflowId: string | null) => boolean
        isWizardStateResolved: (
            hasResolvedSessionState: boolean,
            watchedWorkflows: string[],
            receivedFeatureFlags: boolean,
            verdictWaitExpired: boolean
        ) => boolean
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
            isWizardRunning: boolean,
            isWizardStateResolved: boolean,
            isRefetching: boolean
        ) => InboxOnboardingDecision
        resolvedOnboardingMode: (onboardingDecision: InboxOnboardingDecision) => InboxOnboardingMode
        lastSettledUiState: (
            lastSettledUiStateByTeam: Record<string, InboxSettledUiState>,
            currentTeamId: number | null
        ) => InboxSettledUiState | null
        onboardingMode: (
            resolvedOnboardingMode: InboxOnboardingMode,
            lastSettledUiState: InboxSettledUiState | null
        ) => InboxOnboardingMode
        isWelcomeRedesign: (onboardingMode: InboxOnboardingMode, featureFlags: FeatureFlagsSet) => boolean
    }
}

export type inboxOnboardingLogicType = MakeLogicType<
    inboxOnboardingLogicValues,
    inboxOnboardingLogicActions,
    Record<string, any>,
    inboxOnboardingLogicMeta
>

/**
 * Decides how the single-command self-driving onboarding presents itself. The wizard is the main
 * way in – one command in the user's repo, no in-app steps – so "set up" is read from what ends up
 * watching: at least one signal source or scout. `enabledSourcesCount` counts Replay Vision too,
 * which reaches the inbox on its own, without the wizard ever being run.
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
            signalSourcesLogic,
            ['sourceConfigs', 'sourceConfigsLoading', 'enabledSourcesCount', 'hasEmittingScanner'],
            scoutFleetLogic,
            ['scoutConfigs', 'scoutConfigsLoading', 'enabledCount as enabledScoutsCount'],
            // Mount the pulls + reports count loaders directly (cheap limit=1 each) so we know
            // whether there's existing work even during a takeover, when the tab bar that usually
            // mounts these isn't rendered. Same keyed instances the tab bar uses – no double-fetch.
            reportListLogic({ tabKey: 'pulls', listParams: INBOX_FLAT_TAB_LIST_PARAMS.pulls }),
            ['count as pullsCount', 'countLoading as pullsCountLoading'],
            reportListLogic({ tabKey: 'reports', listParams: INBOX_FLAT_TAB_LIST_PARAMS.reports }),
            ['count as reportsCount', 'countLoading as reportsCountLoading'],
            // Already mounted app-wide by the sync widget; connecting here just reads its verdict.
            wizardActiveSessionDetectorLogic,
            ['activeWorkflowId', 'hasResolvedSessionState', 'watchedWorkflows'],
            featureFlagLogic,
            ['receivedFeatureFlags', 'featureFlags'],
            teamLogic,
            ['currentTeamId'],
        ],
        actions: [
            wizardActiveSessionDetectorLogic,
            ['check as checkWizardSession'],
            signalSourcesLogic,
            ['loadSourceConfigs'],
            scoutFleetLogic,
            ['loadScoutConfigs'],
            reportListLogic({ tabKey: 'pulls', listParams: INBOX_FLAT_TAB_LIST_PARAMS.pulls }),
            ['loadCount as loadPullsCount'],
            reportListLogic({ tabKey: 'reports', listParams: INBOX_FLAT_TAB_LIST_PARAMS.reports }),
            ['loadCount as loadReportsCount'],
        ],
    })),

    actions({
        dismissBanner: true,
        expireWizardVerdictWait: true,
        setLastSettledUiState: (teamId: number, uiState: InboxSettledUiState) => ({ teamId, uiState }),
        refreshSetupState: true,
    }),

    listeners(({ actions }) => ({
        // Re-pull everything the verdict is computed from. Fired when the wizard run ends and when
        // the user returns to a tab whose verdict still says "not set up".
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
        verdictWaitExpired: [
            false,
            {
                expireWizardVerdictWait: () => true,
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
            (s) => [s.enabledSourcesCount, s.enabledScoutsCount],
            (enabledSourcesCount: number, enabledScoutsCount: number): boolean =>
                enabledSourcesCount + enabledScoutsCount > 0,
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
        isWizardRunning: [
            (s) => [s.activeWorkflowId],
            (activeWorkflowId: string | null): boolean => activeWorkflowId === SELF_DRIVING_WORKFLOW_ID,
        ],
        isWizardStateResolved: [
            (s) => [s.hasResolvedSessionState, s.watchedWorkflows, s.receivedFeatureFlags, s.verdictWaitExpired],
            (
                hasResolvedSessionState: boolean,
                watchedWorkflows: string[],
                receivedFeatureFlags: boolean,
                verdictWaitExpired: boolean
            ): boolean =>
                resolveWizardState({
                    hasResolvedSessionState,
                    watchedWorkflows,
                    receivedFeatureFlags,
                    verdictWaitExpired,
                }),
        ],
        // A config or count request is in flight. While true, the verdict must not commit to the
        // takeover: the wizard may just have finished, and the loaded values are about to change.
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
                s.isWizardRunning,
                s.isWizardStateResolved,
                s.isRefetching,
            ],
            (
                isSetupLoaded: boolean,
                isSelfDrivingSetUp: boolean,
                areCountsResolved: boolean,
                hasExistingWork: boolean,
                bannerDismissed: boolean,
                isWizardRunning: boolean,
                isWizardStateResolved: boolean,
                isRefetching: boolean
            ): InboxOnboardingDecision =>
                computeOnboardingDecision({
                    isSetupLoaded,
                    isSelfDrivingSetUp,
                    areCountsResolved,
                    hasExistingWork,
                    bannerDismissed,
                    isWizardRunning,
                    isWizardStateResolved,
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
            (s) => [s.resolvedOnboardingMode, s.lastSettledUiState],
            (
                resolvedOnboardingMode: InboxOnboardingMode,
                lastSettledUiState: InboxSettledUiState | null
            ): InboxOnboardingMode => resolveDisplayMode(resolvedOnboardingMode, lastSettledUiState),
        ],
        // The featureFlags proxy fires the `$feature_flag_called` exposure the moment a flag is
        // read, so the read is guarded on the takeover actually showing: exposure has to mean
        // "this user saw the welcome page", or the experiment dilutes with users who never did.
        // Keyed off the display mode deliberately – a cache-predicted takeover still shows the
        // welcome page, so the exposure is real.
        isWelcomeRedesign: [
            (s) => [s.onboardingMode, s.featureFlags],
            (onboardingMode: InboxOnboardingMode, featureFlags: FeatureFlagsSet): boolean =>
                onboardingMode === 'takeover' && featureFlags[FEATURE_FLAGS.INBOX_WELCOME_REDESIGN] === 'test',
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
        // A wizard run ending in this tab means sources and scouts probably just landed: re-pull
        // them so the verdict flips to the real inbox without a page reload. `isRefetching` holds
        // the takeover back until the fresh data arrives.
        isWizardRunning: (isWizardRunning: boolean, previousIsWizardRunning: boolean | undefined) => {
            if (previousIsWizardRunning === true && !isWizardRunning) {
                actions.refreshSetupState()
            }
        },
    })),

    // The detector's own first poll is jittered up to 30s to spread deploy-reload herds; someone
    // landing in the inbox straight from onboarding can't wait that out with the takeover verdict
    // hanging on the answer. One targeted poll on mount settles it in a request — gated on the
    // verdict actually being pending, so the herd the jitter protects against (every inbox-parked
    // tab reloading on a deploy) isn't reintroduced for users whose takeover can't be suppressed.
    // The gate is pending for the whole self-driving arm on a fresh mount, though, so the poll
    // still keeps a short jitter of its own: a deploy that reloads every inbox-parked tab spreads
    // over a few seconds instead of arriving as one spike, while a user coming from onboarding
    // still gets their answer far inside the 30s window.
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

        if (values.isWizardStateResolved) {
            return
        }
        cache.disposables.add(() => {
            // The plugin re-runs this on every return to a visible tab; the latch keeps it a
            // one-shot rather than a poll of its own.
            if (cache.mountCheckFired) {
                return () => {}
            }
            const id = window.setTimeout(() => {
                cache.mountCheckFired = true
                actions.checkWizardSession()
            }, Math.random() * MOUNT_CHECK_JITTER_MS)
            return () => window.clearTimeout(id)
        }, 'mount-wizard-check')

        // Backstop for a verdict that never lands. Runs while the tab is hidden too: a user who
        // opens the inbox in a background tab and comes back to it should find the prompt already
        // decided, not a timer that only started when they looked.
        cache.disposables.add(
            () => {
                const id = window.setTimeout(() => actions.expireWizardVerdictWait(), WIZARD_VERDICT_DEADLINE_MS)
                return () => window.clearTimeout(id)
            },
            'wizard-verdict-deadline',
            { pauseOnPageHidden: false }
        )
    }),
])
