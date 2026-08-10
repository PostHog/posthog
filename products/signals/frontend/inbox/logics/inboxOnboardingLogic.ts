import { MakeLogicType, actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { captureInboxOnboardingDecided } from '../inboxAnalytics'
import { signalSourcesLogic } from '../signalSourcesLogic'
import type { SignalSourceConfig } from '../types'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from './reportListLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

// Spread for the mount-time wizard check. Short enough that a user arriving from onboarding gets
// their verdict almost immediately, long enough that a fleet-wide reload doesn't land as one spike.
const MOUNT_CHECK_JITTER_MS = 3 * 1000

// Ceiling on how long the wizard verdict may hold the prompt back. The verdict can never arrive:
// the shortcut below needs the feature-flag payload, which an ad blocker can drop entirely, and a
// detector whose endpoint keeps erroring only settles after enough consecutive failures. Both leave
// someone who has not set self-driving up on an inbox that never offers to. Well past the sub-second
// window the guard exists for (jitter plus one request), so capping it costs the normal path nothing.
const WIZARD_VERDICT_DEADLINE_MS = 15 * 1000

/** How the self-driving onboarding presents itself over the inbox. */
export type InboxOnboardingMode = 'takeover' | 'banner' | 'none'

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
 * `'none'` is the default: render the normal inbox, which shows its own list skeleton while loading.
 * We only switch to a takeover/banner once we're *confident* self-driving isn't set up – so we stay
 * on `'none'` (the familiar skeleton) until both the config check and, if needed, the report counts
 * have settled. This avoids flashing the takeover/banner before we know the verdict.
 */
export function computeOnboardingDecision({
    isSetupLoaded,
    isSelfDrivingSetUp,
    areCountsResolved,
    hasExistingWork,
    bannerDismissed,
    isWizardRunning,
    isWizardStateResolved,
}: OnboardingModeInputs): InboxOnboardingDecision {
    // A run in flight is setup in progress: sources and scouts land as it goes, so telling the user
    // to go and run the wizard would contradict the progress widget already showing it running.
    if (isWizardRunning) {
        return { mode: 'none', reason: 'wizard_running' }
    }
    // The config and count loaders settle in under a second; the wizard detector answers on its own
    // polling cadence. Until it has, "not running" is absence of evidence, and acting on it here is
    // exactly the wrong-takeover case for someone landing in the inbox mid-run — so hold the normal
    // inbox, same as the other unsettled inputs below. `resolveWizardState` bounds that wait.
    if (!isWizardStateResolved) {
        return { mode: 'none', reason: 'wizard_state_unknown' }
    }
    // Until the config check resolves we don't know the verdict – stay on the normal inbox skeleton.
    if (!isSetupLoaded) {
        return { mode: 'none', reason: 'setup_loading' }
    }
    // Set-up users go straight to their inbox – no need to wait on the report counts.
    if (isSelfDrivingSetUp) {
        return { mode: 'none', reason: 'already_set_up' }
    }
    // Not set up: the report counts decide takeover (empty inbox) vs. banner (work already exists).
    // Keep the inbox skeleton until they settle, rather than guessing.
    if (!areCountsResolved) {
        return { mode: 'none', reason: 'counts_loading' }
    }
    if (hasExistingWork) {
        return bannerDismissed ? { mode: 'none', reason: 'banner_dismissed' } : { mode: 'banner', reason: null }
    }
    return { mode: 'takeover', reason: null }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxOnboardingLogicValues {
    receivedFeatureFlags: boolean // featureFlagLogic
    pullsCount: number | null // reportListLogic
    pullsCountLoading: boolean // reportListLogic
    reportsCount: number | null // reportListLogic
    reportsCountLoading: boolean // reportListLogic
    enabledScoutsCount: number // scoutFleetLogic
    scoutConfigs: SignalScoutConfig[] | null // scoutFleetLogic
    enabledSourcesCount: number // signalSourcesLogic
    sourceConfigs: SignalSourceConfig[] | null // signalSourcesLogic
    activeWorkflowId: string | null // wizardActiveSessionDetectorLogic
    hasResolvedSessionState: boolean // wizardActiveSessionDetectorLogic
    watchedWorkflows: string[] // wizardActiveSessionDetectorLogic
    areCountsResolved: boolean
    bannerDismissed: boolean
    hasExistingWork: boolean
    isSelfDrivingSetUp: boolean
    isSetupLoaded: boolean
    isWizardRunning: boolean
    isWizardStateResolved: boolean
    onboardingDecision: InboxOnboardingDecision
    onboardingMode: InboxOnboardingMode
    verdictWaitExpired: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxOnboardingLogicActions {
    checkWizardSession: () => {
        value: true
    } // wizardActiveSessionDetectorLogic
    dismissBanner: () => {
        value: true
    }
    expireWizardVerdictWait: () => {
        value: true
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
            receivedFeatureFlags: boolean,
            verdictWaitExpired: boolean
        ) => boolean
        onboardingDecision: (
            isSetupLoaded: boolean,
            isSelfDrivingSetUp: boolean,
            areCountsResolved: boolean,
            hasExistingWork: boolean,
            bannerDismissed: boolean,
            isWizardRunning: boolean,
            isWizardStateResolved: boolean
        ) => InboxOnboardingDecision
        onboardingMode: (onboardingDecision: InboxOnboardingDecision) => InboxOnboardingMode
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
            ['receivedFeatureFlags'],
        ],
        actions: [wizardActiveSessionDetectorLogic, ['check as checkWizardSession']],
    })),

    actions({
        dismissBanner: true,
        expireWizardVerdictWait: true,
    }),

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
        onboardingDecision: [
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
            ): InboxOnboardingDecision =>
                computeOnboardingDecision({
                    isSetupLoaded,
                    isSelfDrivingSetUp,
                    areCountsResolved,
                    hasExistingWork,
                    bannerDismissed,
                    isWizardRunning,
                    isWizardStateResolved,
                }),
        ],
        onboardingMode: [
            (s) => [s.onboardingDecision],
            (onboardingDecision: InboxOnboardingDecision): InboxOnboardingMode => onboardingDecision.mode,
        ],
    }),

    subscriptions(({ cache }) => ({
        // One event per distinct verdict per mount. The decision settles through several
        // intermediate `none`s as its inputs load, so reporting every transition would drown the
        // real answer; deduping on the pair keeps the loading states as the trail that explains it.
        onboardingDecision: (decision: InboxOnboardingDecision) => {
            const key = `${decision.mode}:${decision.reason ?? 'shown'}`
            if (cache.reportedDecisions?.has(key)) {
                return
            }
            cache.reportedDecisions = (cache.reportedDecisions ?? new Set<string>()).add(key)
            captureInboxOnboardingDecided({ mode: decision.mode, reason: decision.reason })
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
