import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'

import {
    computeOnboardingDecision,
    InboxOnboardingDecision,
    OnboardingModeInputs,
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
        }

        it.each<[string, Partial<OnboardingModeInputs>, InboxOnboardingDecision]>([
            // Until the config check resolves, stay on the normal inbox (its own skeleton) – never guess
            // the takeover, which would jolt for a set-up user.
            ['config still loading', { isSetupLoaded: false }, { mode: 'none', reason: 'setup_loading' }],
            // Config not loaded wins even if the set-up flag is incidentally true – we don't trust it yet.
            [
                'config still loading, set-up flag ignored',
                { isSetupLoaded: false, isSelfDrivingSetUp: true },
                { mode: 'none', reason: 'setup_loading' },
            ],
            // Not set up, counts still loading → keep the inbox until we can choose takeover vs banner.
            [
                'not set up, counts still loading',
                { areCountsResolved: false },
                { mode: 'none', reason: 'counts_loading' },
            ],
            // Set up (a source or scout is watching) → no onboarding at all, and no wait on counts.
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
                { mode: 'none', reason: 'wizard_state_unknown' },
            ],
            [
                'wizard state unknown, would otherwise banner',
                { isWizardStateResolved: false, hasExistingWork: true },
                { mode: 'none', reason: 'wizard_state_unknown' },
            ],
        ])('%s', (_label, overrides, expected) => {
            expect(computeOnboardingDecision({ ...base, ...overrides })).toEqual(expected)
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
