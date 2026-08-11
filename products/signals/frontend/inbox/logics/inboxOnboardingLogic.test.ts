import {
    computeOnboardingMode,
    InboxOnboardingMode,
    InboxSettledUiState,
    OnboardingModeInputs,
    resolveDisplayMode,
} from './inboxOnboardingLogic'

describe('inboxOnboardingLogic', () => {
    describe('computeOnboardingMode', () => {
        const base: OnboardingModeInputs = {
            isSetupLoaded: true,
            isSelfDrivingSetUp: false,
            areCountsResolved: true,
            hasExistingWork: false,
            bannerDismissed: false,
            isWizardRunning: false,
            isWizardStateResolved: true,
            isRefetching: false,
        }

        it.each<[string, Partial<OnboardingModeInputs>, InboxOnboardingMode]>([
            // Until the config check resolves the takeover is still on the table – commit to neither
            // UI, or whichever renders first flashes and gets swapped for the other.
            ['config still loading', { isSetupLoaded: false }, 'pending'],
            // Config not loaded wins even if the set-up flag is incidentally true – we don't trust it yet.
            [
                'config still loading, set-up flag ignored',
                { isSetupLoaded: false, isSelfDrivingSetUp: true },
                'pending',
            ],
            // Not set up, counts still loading → they decide takeover vs banner, so keep holding.
            ['not set up, counts still loading', { areCountsResolved: false }, 'pending'],
            // Set up (a source or scout is watching) → no onboarding at all, and no wait on counts.
            ['set up, empty inbox', { isSelfDrivingSetUp: true }, 'none'],
            ['set up, with work', { isSelfDrivingSetUp: true, hasExistingWork: true }, 'none'],
            ['set up, counts unresolved (skipped)', { isSelfDrivingSetUp: true, areCountsResolved: false }, 'none'],
            // ...and no wait on the wizard detector either – its answer can't flip a set-up verdict.
            [
                'set up, wizard state unknown (skipped)',
                { isSelfDrivingSetUp: true, isWizardStateResolved: false },
                'none',
            ],
            // Not set up + nothing in the inbox → full-pane takeover (nothing to block).
            ['not set up, empty inbox', {}, 'takeover'],
            // Not set up but work exists → non-blocking banner, so existing work stays accessible.
            ['not set up, with work', { hasExistingWork: true }, 'banner'],
            // A dismissed banner falls back to the normal inbox for the session.
            ['not set up, with work, banner dismissed', { hasExistingWork: true, bannerDismissed: true }, 'none'],
            // Dismissing the banner has no effect on the takeover (the takeover has no dismiss).
            ['not set up, empty inbox, banner dismissed', { bannerDismissed: true }, 'takeover'],
            // A run in flight is setup in progress: telling the user to go run the wizard would
            // contradict the progress widget already showing it running.
            ['wizard running, would otherwise take over', { isWizardRunning: true }, 'none'],
            ['wizard running, would otherwise banner', { isWizardRunning: true, hasExistingWork: true }, 'none'],
            // Until the detector has actually checked, "not running" is absence of evidence: the
            // config/count loaders settle far faster than the detector's jittered poll, so acting on it
            // would show the takeover to someone landing in the inbox mid-run.
            ['wizard state unknown, would otherwise take over', { isWizardStateResolved: false }, 'pending'],
            // Known work rules the takeover out – every remaining outcome renders the normal inbox, so
            // show it immediately; the banner joins once the remaining checks settle.
            [
                'wizard state unknown, would otherwise banner',
                { isWizardStateResolved: false, hasExistingWork: true },
                'none',
            ],
            ['with work, config still loading', { isSetupLoaded: false, hasExistingWork: true }, 'none'],
            // A refetch in flight (wizard just finished, or the user came back to the tab) means
            // the loaded values may be stale – never commit to the takeover on them.
            ['refetch in flight, would otherwise take over', { isRefetching: true }, 'pending'],
            // The refetch hold only guards the takeover; settled inbox verdicts stay put.
            ['refetch in flight, set up', { isRefetching: true, isSelfDrivingSetUp: true }, 'none'],
            ['refetch in flight, with work', { isRefetching: true, hasExistingWork: true }, 'banner'],
        ])('%s', (_label, overrides, expected) => {
            expect(computeOnboardingMode({ ...base, ...overrides })).toBe(expected)
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
})
