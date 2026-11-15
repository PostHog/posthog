import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import {
    computeIsSelfDrivingSetUp,
    computeOnboardingDecision,
    InboxOnboardingDecision,
    InboxOnboardingMode,
    InboxSettledUiState,
    OnboardingModeInputs,
    resolveDisplayMode,
} from './inboxOnboardingLogic'

describe('inboxOnboardingLogic', () => {
    describe('computeOnboardingDecision', () => {
        const base: OnboardingModeInputs = {
            isSetupLoaded: true,
            isSelfDrivingSetUp: false,
            areCountsResolved: true,
            hasExistingWork: false,
            bannerDismissed: false,
            isRefetching: false,
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
            // Known work rules the takeover out – every remaining outcome renders the normal inbox, so
            // show it immediately; the banner joins once the remaining checks settle.
            [
                'with work, config still loading',
                { isSetupLoaded: false, hasExistingWork: true },
                { mode: 'none', reason: 'setup_loading' },
            ],
            // A refetch in flight (the user came back to the tab) means
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
        ])('%s', (_label, overrides, expected) => {
            expect(computeOnboardingDecision({ ...base, ...overrides })).toEqual(expected)
        })
    })

    describe('computeIsSelfDrivingSetUp', () => {
        type Scout = Pick<SignalScoutConfigApi, 'enabled' | 'managed_by' | 'scout_role'>
        const background: Scout = { enabled: true, managed_by: 'background', scout_role: 'specialist' }
        const operational: Scout = { enabled: true, managed_by: 'team', scout_role: 'operational' }
        const specialist: Scout = { enabled: true, managed_by: 'team', scout_role: 'specialist' }

        it.each<[string, number, Scout[] | null, boolean]>([
            ['configs not loaded', 0, null, false],
            ['background scout only', 0, [background], false],
            // The first inbox visit seeds the operational scouts enabled, so they must not end onboarding.
            ['background scout plus seeded operational scout', 0, [background, operational], false],
            ['operational scout only', 0, [operational], false],
            ['person enabled a specialist scout', 0, [operational, specialist], true],
            ['disabled specialist scout', 0, [{ ...specialist, enabled: false }], false],
            ['enabled source', 1, [operational], true],
        ])('%s', (_label, enabledSourcesCount, scoutConfigs, expected) => {
            expect(computeIsSelfDrivingSetUp(enabledSourcesCount, scoutConfigs)).toBe(expected)
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
