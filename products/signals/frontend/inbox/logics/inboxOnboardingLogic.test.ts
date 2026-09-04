import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'

import {
    computeOnboardingDecision,
    InboxOnboardingDecision,
    InboxOnboardingMode,
    InboxSettledUiState,
    OnboardingModeInputs,
    resolveDisplayMode,
    resolveWizardState,
    WizardStateInputs,
} from './inboxOnboardingLogic'

describe('inboxOnboardingLogic', () => {
    describe('computeOnboardingDecision', () => {
        const base: OnboardingModeInputs = {
            isSetupLoaded: true,
            isSelfDrivingSetUp: false,
            areCountsResolved: true,
            hasExistingWork: false,
            bannerDismissed: false,
            isWizardRunning: false,
            isWizardStateResolved: true,
            isRefetching: false,
            manualSetupRequested: false,
        }

        it.each<[string, Partial<OnboardingModeInputs>, InboxOnboardingDecision]>([
            // Until the config check resolves the takeover is still on the table – commit to neither
            // UI, or whichever renders first flashes and gets swapped for the other.
            ['config still loading', { isSetupLoaded: false }, { mode: 'pending', reason: 'setup_loading' }],
            // Config not loaded wins even if the set-up flag is incidentally true – we don't trust it yet.
            [
                'config still loading, set-up flag ignored',
                { isSetupLoaded: false, isSelfDrivingSetUp: true },
                { mode: 'pending', reason: 'setup_loading' },
            ],
            // Not set up, counts still loading → they decide takeover vs banner, so keep holding.
            [
                'not set up, counts still loading',
                { areCountsResolved: false },
                { mode: 'pending', reason: 'counts_loading' },
            ],
            // Set up (a source, scout, or scanner is watching) → no onboarding at all, and no wait on counts.
            ['set up, empty inbox', { isSelfDrivingSetUp: true }, { mode: 'none', reason: 'already_set_up' }],
            [
                'set up, with work',
                { isSelfDrivingSetUp: true, hasExistingWork: true },
                { mode: 'none', reason: 'already_set_up' },
            ],
            [
                'set up, counts unresolved (skipped)',
                { isSelfDrivingSetUp: true, areCountsResolved: false },
                { mode: 'none', reason: 'already_set_up' },
            ],
            // ...and no wait on the wizard detector either – its answer can't flip a set-up verdict.
            [
                'set up, wizard state unknown (skipped)',
                { isSelfDrivingSetUp: true, isWizardStateResolved: false },
                { mode: 'none', reason: 'already_set_up' },
            ],
            // Not set up + nothing in the inbox → full-pane takeover (nothing to block).
            ['not set up, empty inbox', {}, { mode: 'takeover', reason: null }],
            // Not set up but work exists → non-blocking banner, so existing work stays accessible.
            ['not set up, with work', { hasExistingWork: true }, { mode: 'banner', reason: null }],
            // A dismissed banner falls back to the normal inbox for the session.
            [
                'not set up, with work, banner dismissed',
                { hasExistingWork: true, bannerDismissed: true },
                { mode: 'none', reason: 'banner_dismissed' },
            ],
            // Dismissing the banner has no effect on the takeover (the takeover has no dismiss).
            [
                'not set up, empty inbox, banner dismissed',
                { bannerDismissed: true },
                { mode: 'takeover', reason: null },
            ],
            // A run in flight is setup in progress: telling the user to go run the wizard would
            // contradict the progress widget already showing it running.
            [
                'wizard running, would otherwise take over',
                { isWizardRunning: true },
                { mode: 'none', reason: 'wizard_running' },
            ],
            [
                'wizard running, would otherwise banner',
                { isWizardRunning: true, hasExistingWork: true },
                { mode: 'none', reason: 'wizard_running' },
            ],
            // Until the detector has actually checked, "not running" is absence of evidence: the
            // config/count loaders settle far faster than the detector's jittered poll, so acting on it
            // would show the takeover to someone landing in the inbox mid-run.
            [
                'wizard state unknown, would otherwise take over',
                { isWizardStateResolved: false },
                { mode: 'pending', reason: 'wizard_state_unknown' },
            ],
            // Known work rules the takeover out – every remaining outcome renders the normal inbox, so
            // show it immediately; the banner joins once the remaining checks settle.
            [
                'wizard state unknown, would otherwise banner',
                { isWizardStateResolved: false, hasExistingWork: true },
                { mode: 'none', reason: 'wizard_state_unknown' },
            ],
            [
                'with work, config still loading',
                { isSetupLoaded: false, hasExistingWork: true },
                { mode: 'none', reason: 'setup_loading' },
            ],
            // A refetch in flight (wizard just finished, or the user came back to the tab) means
            // the loaded values may be stale – never commit to the takeover on them.
            [
                'refetch in flight, would otherwise take over',
                { isRefetching: true },
                { mode: 'pending', reason: 'refetching' },
            ],
            // The refetch hold only guards the takeover; settled inbox verdicts stay put.
            [
                'refetch in flight, set up',
                { isRefetching: true, isSelfDrivingSetUp: true },
                { mode: 'none', reason: 'already_set_up' },
            ],
            [
                'refetch in flight, with work',
                { isRefetching: true, hasExistingWork: true },
                { mode: 'banner', reason: null },
            ],
            // "Set up manually" opens the Configuration and Scouts tabs the takeover was covering,
            // so the whole prompt stands down for the session.
            [
                'manual setup requested, would otherwise take over',
                { manualSetupRequested: true },
                { mode: 'none', reason: 'manual_setup' },
            ],
            // Enabling a source or scout from there is the real end state, so `already_set_up` wins
            // and the takeover can never come back, session flag or not.
            [
                'manual setup requested, now set up',
                { manualSetupRequested: true, isSelfDrivingSetUp: true },
                { mode: 'none', reason: 'already_set_up' },
            ],
            // A run in flight still outranks it: the progress widget is the more accurate story.
            [
                'manual setup requested, wizard running',
                { manualSetupRequested: true, isWizardRunning: true },
                { mode: 'none', reason: 'wizard_running' },
            ],
        ])('%s', (_label, overrides, expected) => {
            expect(computeOnboardingDecision({ ...base, ...overrides })).toEqual(expected)
        })
    })

    describe('resolveDisplayMode', () => {
        it.each<[string, InboxOnboardingMode, InboxSettledUiState | null, InboxOnboardingMode]>([
            // A settled verdict always wins – the cache must never override live inputs.
            ['settled none ignores cached takeover', 'none', 'takeover', 'none'],
            ['settled takeover ignores cached inbox', 'takeover', 'inbox', 'takeover'],
            ['settled banner ignores cache', 'banner', 'takeover', 'banner'],
            // While the verdict is settling, paint what this team saw last visit.
            ['pending falls back to cached takeover', 'pending', 'takeover', 'takeover'],
            ['pending falls back to cached inbox', 'pending', 'inbox', 'none'],
            // No history (very first visit) → the neutral skeleton.
            ['pending with no cache stays pending', 'pending', null, 'pending'],
        ])('%s', (_label, resolvedMode, lastSettledUiState, expected) => {
            expect(resolveDisplayMode(resolvedMode, lastSettledUiState)).toBe(expected)
        })
    })

    describe('resolveWizardState', () => {
        const base: WizardStateInputs = {
            hasResolvedSessionState: false,
            watchedWorkflows: [SELF_DRIVING_WORKFLOW_ID],
            receivedFeatureFlags: true,
            verdictWaitExpired: false,
        }

        it.each<[string, Partial<WizardStateInputs>, boolean]>([
            // The detector answered, so `isWizardRunning` can be acted on however it landed.
            ['detector settled', { hasResolvedSessionState: true }, true],
            // Not watching the self-driving program: the detector's verdict could never flip
            // `isWizardRunning`, so waiting on it would cost every inbox user a hold for nothing.
            ['not watching the self-driving program', { watchedWorkflows: [] }, true],
            // The shortcut above needs flags in hand — without them every user reads as the control
            // arm, which would show the takeover to someone mid-run and then snatch it back.
            ['not watching, but flags not in yet', { watchedWorkflows: [], receivedFeatureFlags: false }, false],
            // Watching and unsettled is the one case that genuinely has no answer yet.
            ['watching, detector still pending', {}, false],
            // The backstop. Without it, a flag payload an ad blocker drops or a detector whose polls
            // keep erroring hides the only prompt to set self-driving up, for the whole session.
            ['deadline elapsed with no verdict', { verdictWaitExpired: true }, true],
            ['deadline elapsed with no flags either', { receivedFeatureFlags: false, verdictWaitExpired: true }, true],
        ])('%s', (_label, overrides, expected) => {
            expect(resolveWizardState({ ...base, ...overrides })).toBe(expected)
        })
    })
})
