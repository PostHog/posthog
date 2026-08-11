import { MakeLogicType, actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { signalSourcesLogic } from '../signalSourcesLogic'
import type { SignalSourceConfig } from '../types'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from './reportListLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

// Spread for the mount-time wizard check. Short enough that a user arriving from onboarding gets
// their verdict almost immediately, long enough that a fleet-wide reload doesn't land as one spike.
const MOUNT_CHECK_JITTER_MS = 3 * 1000

/** How the self-driving onboarding presents itself over the inbox. */
export type InboxOnboardingMode = 'takeover' | 'banner' | 'none' | 'pending'

/** What the inbox rendered last time the verdict settled: the welcome takeover, or the normal
 * inbox (with or without the banner). Cached per team so the next visit shows it instantly. */
export type InboxSettledUiState = 'takeover' | 'inbox'

/** localStorage key for the per-team last-settled UI state (see `lastSettledUiStateByTeam`). */
export const INBOX_LAST_UI_STATE_STORAGE_KEY = 'inbox-onboarding-last-ui-state'

export interface OnboardingModeInputs {
    /** Both source + scout config loaders have settled, so the set-up verdict is trustworthy. */
    isSetupLoaded: boolean
    /** At least one signal source or scout is watching. */
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
 */
export function computeOnboardingMode({
    isSetupLoaded,
    isSelfDrivingSetUp,
    areCountsResolved,
    hasExistingWork,
    bannerDismissed,
    isWizardRunning,
    isWizardStateResolved,
}: OnboardingModeInputs): InboxOnboardingMode {
    // A run in flight is setup in progress: sources and scouts land as it goes, so telling the user
    // to go and run the wizard would contradict the progress widget already showing it running.
    if (isWizardRunning) {
        return 'none'
    }
    // Set-up users go straight to their inbox the moment the config check lands – neither the
    // wizard detector nor the report counts could flip their verdict to an onboarding.
    if (isSetupLoaded && isSelfDrivingSetUp) {
        return 'none'
    }
    // Work already in the inbox rules the takeover out: the only remaining outcomes (banner /
    // none) both render the normal inbox, so show it now rather than holding a skeleton. The
    // non-blocking banner joins once the config and wizard checks settle.
    if (areCountsResolved && hasExistingWork) {
        if (!isSetupLoaded || !isWizardStateResolved) {
            return 'none'
        }
        return bannerDismissed ? 'none' : 'banner'
    }
    // The takeover is still possible. Until every input has settled – configs (is anything
    // watching?), counts (is there work to keep?), and the wizard detector (is a run in flight?) –
    // committing to either UI risks flashing it and swapping it out, so hold the neutral skeleton.
    if (!isSetupLoaded || !isWizardStateResolved || !areCountsResolved) {
        return 'pending'
    }
    return 'takeover'
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
    enabledSourcesCount: number // signalSourcesLogic
    sourceConfigs: SignalSourceConfig[] | null // signalSourcesLogic
    currentTeamId: number | null // teamLogic
    activeWorkflowId: string | null // wizardActiveSessionDetectorLogic
    hasResolvedSessionState: boolean // wizardActiveSessionDetectorLogic
    watchedWorkflows: string[] // wizardActiveSessionDetectorLogic
    areCountsResolved: boolean
    bannerDismissed: boolean
    hasExistingWork: boolean
    isSelfDrivingSetUp: boolean
    isSetupLoaded: boolean
    isWelcomeRedesign: boolean
    isWizardRunning: boolean
    isWizardStateResolved: boolean
    lastSettledUiState: InboxSettledUiState | null
    lastSettledUiStateByTeam: Record<string, InboxSettledUiState>
    onboardingMode: InboxOnboardingMode
    resolvedOnboardingMode: InboxOnboardingMode
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxOnboardingLogicActions {
    checkWizardSession: () => {
        value: true
    } // wizardActiveSessionDetectorLogic
    dismissBanner: () => {
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
        isSetupLoaded: (sourceConfigs: SignalSourceConfig[] | null, scoutConfigs: SignalScoutConfig[] | null) => boolean
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
            receivedFeatureFlags: boolean
        ) => boolean
        resolvedOnboardingMode: (
            isSetupLoaded: boolean,
            isSelfDrivingSetUp: boolean,
            areCountsResolved: boolean,
            hasExistingWork: boolean,
            bannerDismissed: boolean,
            isWizardRunning: boolean,
            isWizardStateResolved: boolean
        ) => InboxOnboardingMode
        lastSettledUiState: (lastSettledUiStateByTeam: any, currentTeamId: any) => InboxSettledUiState | null
        onboardingMode: (resolvedOnboardingMode: any, lastSettledUiState: any) => InboxOnboardingMode
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
 * Decides how the single-command self-driving onboarding presents itself. There are no in-app
 * setup steps – the user runs one wizard command in their repo – so "set up" is read straight
 * from what the wizard turns on: at least one signal source or scout watching.
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
            ['sourceConfigs', 'enabledSourcesCount'],
            scoutFleetLogic,
            ['scoutConfigs', 'enabledCount as enabledScoutsCount'],
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
        actions: [wizardActiveSessionDetectorLogic, ['check as checkWizardSession']],
    })),

    actions({
        dismissBanner: true,
        setLastSettledUiState: (teamId: number, uiState: InboxSettledUiState) => ({ teamId, uiState }),
    }),

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
            (s) => [s.enabledSourcesCount, s.enabledScoutsCount],
            (enabledSourcesCount: number, enabledScoutsCount: number): boolean =>
                enabledSourcesCount + enabledScoutsCount > 0,
        ],
        // Both source + scout config loaders have settled, so the set-up verdict is trustworthy.
        isSetupLoaded: [
            (s) => [s.sourceConfigs, s.scoutConfigs],
            (
                sourceConfigs: import('../types').SignalSourceConfig[] | null,
                scoutConfigs: SignalScoutConfig[] | null
            ): boolean => sourceConfigs !== null && scoutConfigs !== null,
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
        // Trivially resolved when the detector isn't watching the self-driving program (control
        // variant, no surface registered): its verdict could never flip `isWizardRunning`, so
        // waiting on it — or polling eagerly for it — would cost every inbox user something for
        // nothing. That shortcut needs flags in hand though: `watchedWorkflows` is derived from the
        // onboarding variant, and before the flags land it reads as the control arm for everyone,
        // which would let the takeover render for a user whose run is mid-flight and then flicker
        // back out once the flags arrive.
        isWizardStateResolved: [
            (s) => [s.hasResolvedSessionState, s.watchedWorkflows, s.receivedFeatureFlags],
            (hasResolvedSessionState: boolean, watchedWorkflows: string[], receivedFeatureFlags: boolean): boolean =>
                hasResolvedSessionState ||
                (receivedFeatureFlags && !watchedWorkflows.includes(SELF_DRIVING_WORKFLOW_ID)),
        ],
        // The verdict from live inputs alone – 'pending' while they're still settling. Kept
        // separate from `onboardingMode` so the cache writer below never re-persists a guess
        // that itself came from the cache.
        resolvedOnboardingMode: [
            (s) => [
                s.isSetupLoaded,
                s.isSelfDrivingSetUp,
                s.areCountsResolved,
                s.hasExistingWork,
                s.bannerDismissed,
                s.isWizardRunning,
                s.isWizardStateResolved,
            ],
            (
                isSetupLoaded: boolean,
                isSelfDrivingSetUp: boolean,
                areCountsResolved: boolean,
                hasExistingWork: boolean,
                bannerDismissed: boolean,
                isWizardRunning: boolean,
                isWizardStateResolved: boolean
            ): InboxOnboardingMode =>
                computeOnboardingMode({
                    isSetupLoaded,
                    isSelfDrivingSetUp,
                    areCountsResolved,
                    hasExistingWork,
                    bannerDismissed,
                    isWizardRunning,
                    isWizardStateResolved,
                }),
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

    subscriptions(({ actions, values }) => ({
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
    }),
])
