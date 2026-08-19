import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    ReviewHogReviewsListScope,
    ReviewTriggerRequestRunModeEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import {
    MAX_REVIEWS_LIMIT,
    REVIEW_SKILL_PREFIX_BY_KIND,
    REVIEWS_PAGE_SIZE,
    defaultAdoptSlug,
    reviewHogSettingsLogic,
    validateAdoptSlug,
} from './reviewHogSettingsLogic'

/** A minimal review detail: only the fields the drawer selectors read. */
function reviewDetail(id: string, runUrgencyThreshold: string | null): Record<string, any> {
    return {
        id,
        published: false,
        run_urgency_threshold: runUrgencyThreshold,
        findings: [
            { title: 'blocker', effective_priority: 'must_fix' },
            { title: 'recommended', effective_priority: 'should_fix' },
        ],
        dismissed_findings: [],
    }
}

// More project-wide reviews than the API's maximum limit, so both "Show more" growth and its
// ceiling are reachable.
const everyoneReviews = Array.from({ length: MAX_REVIEWS_LIMIT + REVIEWS_PAGE_SIZE }, (_, i) => ({
    id: `r${i}`,
    in_progress: false,
}))

describe('reviewHogSettingsLogic', () => {
    let logic: ReturnType<typeof reviewHogSettingsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                // The user has no reviews of their own; the project has a dozen.
                '/api/projects/:team_id/review_hog/reviews/': ({ request }) => {
                    const url = new URL(request.url)
                    const limit = Number(url.searchParams.get('limit') ?? REVIEWS_PAGE_SIZE)
                    const pool =
                        url.searchParams.get('scope') === ReviewHogReviewsListScope.Everyone ? everyoneReviews : []
                    return [200, { results: pool.slice(0, limit), has_more: pool.length > limit }]
                },
                '/api/projects/:team_id/review_hog/reviews/perspective_stats/': () => [
                    200,
                    { report_count: 0, perspectives: [] },
                ],
                '/api/projects/:team_id/review_hog/settings/': () => [
                    200,
                    {
                        review_inbox_prs: false,
                        review_labeled_prs: true,
                        resolve_comments: true,
                        urgency_threshold: 'should_fix',
                    },
                ],
                '/api/projects/:team_id/review_hog/perspectives/': () => [200, []],
                '/api/projects/:team_id/review_hog/blind_spots/': () => [200, []],
                '/api/projects/:team_id/review_hog/validators/': () => [200, []],
                '/api/projects/:team_id/review_hog/resolution/': () => [200, []],
            },
            post: {
                '/api/projects/:team_id/review_hog/reviews/trigger/': () => [
                    202,
                    { workflow_id: 'wf-1', status: 'started' },
                ],
            },
        })
        // The scope reducers persist; without this a prior test's explicit choice leaks over.
        localStorage.clear()
        initKeaTests()
        logic = reviewHogSettingsLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('auto-defaults to the entire project when the user has no reviews of their own', async () => {
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadRecentReviewsSuccess', 'applyDefaultReviewsScope', 'loadRecentReviewsSuccess'])
            .toMatchValues({
                reviewsScope: ReviewHogReviewsListScope.Everyone,
                // The auto-default is not an explicit choice — a later real one must still win.
                hasUserChosenReviewsScope: false,
            })
        expect(logic.values.recentReviews).toHaveLength(REVIEWS_PAGE_SIZE)
        // The auto-default must not write the URL: hydrating `?reviews_scope=` from a link marks
        // the scope as explicitly chosen, so mirroring the fallback would make it permanent.
        expect(router.values.searchParams.reviews_scope).toBeUndefined()
    })

    it('a started review clears the input, reloads the list, and resets the in-flight flag', async () => {
        logic.mount()
        // Consume the mount-time auto-default so its loadRecentReviews can't satisfy the assertion below.
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        await expectLogic(logic, () => logic.actions.submitTriggerReview())
            .toDispatchActions([
                'submitTriggerReview',
                'startTriggeredReviewWatch',
                'loadRecentReviews',
                'submitTriggerReviewFinished',
            ])
            .toMatchValues({ triggeringReview: false, triggerPrUrl: '' })
        // The report row is created seconds after the 202; the watch keeps the list polling until
        // it appears — without it the poll only arms when another review is already running.
        expect(logic.values.awaitingTriggeredReview).toBe(true)
    })

    it('a repeat submit while a request is in flight does not start a second review', async () => {
        // The disabled button can't stop an Enter keypress in the input, so the listener must drop
        // repeats itself — without the guard each keypress POSTs another trigger.
        let triggerCalls = 0
        useMocks({
            post: {
                '/api/projects/:team_id/review_hog/reviews/trigger/': () => {
                    triggerCalls++
                    return [202, { workflow_id: 'wf-1', status: 'started' }]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        logic.actions.submitTriggerReview()
        logic.actions.submitTriggerReview()
        await expectLogic(logic).toDispatchActions(['submitTriggerReviewFinished'])

        expect(triggerCalls).toBe(1)
    })

    it('a resolve-only run sends its mode and does not arm the review watch', async () => {
        // Resolve-only runs never create the report row the watch polls for — arming it would poll
        // idle for two minutes; and dropping run_mode from the POST would silently degrade the
        // split button's side actions into plain reviews.
        let requestBody: Record<string, unknown> | null = null
        useMocks({
            post: {
                '/api/projects/:team_id/review_hog/reviews/trigger/': async ({ request }) => {
                    requestBody = (await request.json()) as Record<string, unknown>
                    return [202, { workflow_id: 'wf-resolve-1', status: 'started' }]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        await expectLogic(logic, () =>
            logic.actions.submitTriggerReview(ReviewTriggerRequestRunModeEnumApi.ResolveOnly)
        )
            .toDispatchActions(['submitTriggerReview', 'loadRecentReviews', 'submitTriggerReviewFinished'])
            .toNotHaveDispatchedActions(['startTriggeredReviewWatch'])
            .toMatchValues({ triggeringReview: false, triggerPrUrl: '', awaitingTriggeredReview: false })
        expect(requestBody).toMatchObject({ run_mode: 'resolve_only' })
    })

    it('an already-reviewed PR informs without arming the watch', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/review_hog/reviews/trigger/': () => [
                    200,
                    { workflow_id: '', status: 'already_reviewed' },
                ],
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        // Arming the watch here would poll for two minutes waiting for a run that never starts.
        await expectLogic(logic, () => logic.actions.submitTriggerReview())
            .toDispatchActions(['submitTriggerReview', 'loadRecentReviews', 'submitTriggerReviewFinished'])
            .toNotHaveDispatchedActions(['startTriggeredReviewWatch'])
            .toMatchValues({ triggeringReview: false, triggerPrUrl: '', awaitingTriggeredReview: false })
    })

    it('a rejected trigger resets the in-flight flag and keeps the input for correction', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/review_hog/reviews/trigger/': () => [
                    403,
                    { error: "ReviewHog reviews can't be started from this project yet" },
                ],
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        await expectLogic(logic, () => logic.actions.submitTriggerReview())
            .toDispatchActions(['submitTriggerReview', 'submitTriggerReviewFinished'])
            .toNotHaveDispatchedActions(['loadRecentReviews', 'startTriggeredReviewWatch'])
            .toMatchValues({
                triggeringReview: false,
                triggerPrUrl: 'https://github.com/PostHog/posthog.com/pull/1',
                awaitingTriggeredReview: false,
            })
    })

    it('the scope switch rescopes the effectiveness stats along with the list', async () => {
        // The page-level switch must move the stat cards and the reviews list together — dropping
        // the stats reload from the scope listeners (or the scope param from the request) would
        // show one scope's list over the other scope's numbers, the exact confusion the switch
        // exists to fix.
        const statsScopes: (string | null)[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/reviews/perspective_stats/': ({ request }) => {
                    statsScopes.push(new URL(request.url).searchParams.get('scope'))
                    return [200, { report_count: 0, perspectives: [] }]
                },
            },
        })
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadRecentReviewsSuccess', 'applyDefaultReviewsScope', 'loadRecentReviewsSuccess'])
            .toFinishAllListeners()
        // The mount-time auto-default to Entire project already rescoped the stats.
        expect(statsScopes[statsScopes.length - 1]).toBe(ReviewHogReviewsListScope.Everyone)

        logic.actions.setReviewsScope(ReviewHogReviewsListScope.Mine)
        // Old data drops synchronously so neither the cards nor the list ever show the other
        // scope's content — even if the reload were to fail.
        expect(logic.values.perspectiveStats).toBeNull()
        expect(logic.values.recentReviews).toBeNull()
        await expectLogic(logic).toDispatchActions(['loadPerspectiveStatsSuccess'])
        expect(statsScopes[statsScopes.length - 1]).toBe(ReviewHogReviewsListScope.Mine)
    })

    it('respects an explicit scope choice even when that scope is empty', async () => {
        logic.mount()
        // Consume the mount-time auto-default, so the not-dispatched window below starts after it.
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])

        await expectLogic(logic, () => logic.actions.setReviewsScope(ReviewHogReviewsListScope.Mine))
            .toDispatchActions(['loadRecentReviewsSuccess'])
            .toNotHaveDispatchedActions(['applyDefaultReviewsScope'])
            .toMatchValues({
                reviewsScope: ReviewHogReviewsListScope.Mine,
                hasUserChosenReviewsScope: true,
                recentReviews: [],
            })
    })

    it('grows the list by a page per "Show more" and collapses instantly on "Show fewer"', async () => {
        logic.mount()
        // Land on the everyone scope (auto-default) with the first page loaded.
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])
        expect(logic.values.moreReviewsAvailable).toBe(true)

        await expectLogic(logic, () => logic.actions.showMoreReviews())
            .toDispatchActions(['loadRecentReviewsSuccess'])
            .toMatchValues({ reviewsLimit: REVIEWS_PAGE_SIZE * 2 })
        expect(logic.values.recentReviews).toHaveLength(REVIEWS_PAGE_SIZE * 2)

        // The collapse must not wait for the reconciling refetch, and hiding loaded rows means
        // "Show more" must stay on offer regardless of the last response's flag.
        logic.actions.showFewerReviews()
        expect(logic.values.recentReviews).toHaveLength(REVIEWS_PAGE_SIZE)
        expect(logic.values.moreReviewsAvailable).toBe(true)
        await expectLogic(logic).toDispatchActions(['loadRecentReviewsSuccess']).toMatchValues({
            reviewsLimit: REVIEWS_PAGE_SIZE,
        })

        // A scope flip is a different list — it starts compact again.
        logic.actions.showMoreReviews()
        logic.actions.setReviewsScope(ReviewHogReviewsListScope.Mine)
        await expectLogic(logic).toMatchValues({ reviewsLimit: REVIEWS_PAGE_SIZE })
    })

    it('buckets drawer findings by the stored run threshold, with the viewer proxy only for old rows', async () => {
        // The run gated at must_fix while the viewer's own setting (mocked above) is should_fix.
        // Bucketing by the viewer's setting would show the held-back should_fix finding as
        // published — the exact lie the stored snapshot exists to fix.
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/reviews/r-stamped/': () => [
                    200,
                    reviewDetail('r-stamped', 'must_fix'),
                ],
                '/api/projects/:team_id/review_hog/reviews/r-old/': () => [200, reviewDetail('r-old', null)],
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSettingsSuccess'])

        logic.actions.openReviewDetailById('r-stamped')
        await expectLogic(logic).toDispatchActions(['loadReviewDetailSuccess'])
        expect(logic.values.reviewFindingsSplit?.published.map((f) => f.title)).toEqual(['blocker'])
        expect(logic.values.reviewFindingsSplit?.belowThreshold.map((f) => f.title)).toEqual(['recommended'])

        // A pre-column row (null stored threshold) keeps the old viewer-settings approximation.
        logic.actions.openReviewDetailById('r-old')
        await expectLogic(logic).toDispatchActions(['loadReviewDetailSuccess'])
        expect(logic.values.reviewFindingsSplit?.published.map((f) => f.title)).toEqual(['blocker', 'recommended'])
        expect(logic.values.reviewFindingsSplit?.belowThreshold).toEqual([])
    })

    it('opens a review from ?review= and mirrors drawer state back to the URL', async () => {
        // ?review=<report id> is a permanent public contract: PR status comments bake this exact
        // param into their "View them in PostHog" links, so renaming the param or dropping the URL
        // sync silently dead-ends every held-back-findings link already posted to GitHub.
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/reviews/r-9/': () => [200, reviewDetail('r-9', null)],
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecentReviewsSuccess'])

        router.actions.push(urls.codeReview(), { review: 'r-9' })
        await expectLogic(logic)
            .toDispatchActions(['openReviewDetailById', 'loadReviewDetailSuccess'])
            // No list row on a deep link — the drawer must render from the loaded detail alone.
            .toMatchValues({ reviewDrawerOpen: true, openedReview: null })
        expect(logic.values.reviewDetail?.id).toBe('r-9')

        // A repeat location event for the same review (e.g. the open's own URL write-back) must not
        // re-dispatch into the already-open drawer and reload the detail forever.
        await expectLogic(logic, () =>
            router.actions.push(urls.codeReview(), { review: 'r-9' })
        ).toNotHaveDispatchedActions(['openReviewDetailById'])

        // Closing removes the param in place (replace, not push), so back doesn't reopen the drawer.
        logic.actions.closeReviewDrawer()
        expect(logic.values.reviewDrawerOpen).toBe(false)
        expect(router.values.searchParams.review).toBeUndefined()

        // And navigation that drops the param closes an open drawer — the URL and the visible
        // report must never disagree.
        router.actions.push(urls.codeReview(), { review: 'r-9' })
        await expectLogic(logic).toDispatchActions(['openReviewDetailById'])
        router.actions.push(urls.codeReview(), {})
        expect(logic.values.reviewDrawerOpen).toBe(false)
    })

    it('closes a deep-linked drawer when the review fails to load', async () => {
        // A stale ?review= link (deleted report, wrong project) has no list row to fall back on —
        // without the failure path the drawer would sit open on skeletons forever.
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/reviews/r-gone/': () => [404, { detail: 'Not found.' }],
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecentReviewsSuccess'])

        router.actions.push(urls.codeReview(), { review: 'r-gone' })
        await expectLogic(logic).toDispatchActions([
            'openReviewDetailById',
            'loadReviewDetailFailure',
            'closeReviewDrawer',
        ])
        expect(logic.values.reviewDrawerOpen).toBe(false)
        expect(router.values.searchParams.review).toBeUndefined()
    })

    it('stops "Show more" at the API\'s maximum limit', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])

        // Enough clicks to push an unclamped limit past the API's max, where the request would 400
        // and strand the user on a dead button.
        for (let i = 0; i < MAX_REVIEWS_LIMIT / REVIEWS_PAGE_SIZE; i++) {
            logic.actions.showMoreReviews()
        }
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.reviewsLimit).toBe(MAX_REVIEWS_LIMIT)
        expect(logic.values.recentReviews).toHaveLength(MAX_REVIEWS_LIMIT)
        // More rows exist server-side, but the ceiling is reached — the button goes away rather
        // than offering a request the server rejects.
        expect(logic.values.moreReviewsAvailable).toBe(false)
    })

    it('keeps a slower baseline poll running when nothing is in progress', async () => {
        // Reviews started outside this page (the GitHub label, inbox auto-reviews, a teammate)
        // only ever appear via the baseline poll — reverting to dispose-on-idle makes the page
        // permanently stale until a manual refresh.
        jest.useFakeTimers()
        try {
            logic.mount()
            await expectLogic(logic).toDispatchActions([
                'loadRecentReviewsSuccess',
                'applyDefaultReviewsScope',
                'loadRecentReviewsSuccess',
            ])

            await expectLogic(logic, () => {
                jest.advanceTimersByTime(30_000)
            }).toDispatchActions(['loadRecentReviews', 'loadRecentReviewsSuccess'])
        } finally {
            jest.useRealTimers()
        }
    })

    it('refreshes the stats and an open drawer when a watched run finishes', async () => {
        // A poll response is the only place a completion becomes visible: without the fan-out the
        // proof/effectiveness cards and an open drawer keep pre-completion numbers until reload.
        let finished = false
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/reviews/': () => [
                    200,
                    {
                        results: [{ id: 'r-live', in_progress: !finished, run_count: finished ? 1 : 0 }],
                        has_more: false,
                    },
                ],
                '/api/projects/:team_id/review_hog/reviews/r-live/': () => [200, reviewDetail('r-live', null)],
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecentReviewsSuccess']).toFinishAllListeners()

        logic.actions.openReviewDetailById('r-live')
        await expectLogic(logic).toDispatchActions(['loadReviewDetailSuccess'])

        finished = true
        await expectLogic(logic, () => logic.actions.loadRecentReviews()).toDispatchActions([
            'loadRecentReviewsSuccess',
            'loadPerspectiveStats',
            'loadReviewDetail',
        ])
    })

    it('keeps the failure banner off for a background refresh blip', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])
        useMocks({ get: { '/api/projects/:team_id/review_hog/reviews/': () => [500, {}] } })

        // The poll retries on its next tick and the prior rows stay on screen — flashing the
        // page-level banner over one blip would cry wolf every time a request hiccups.
        await expectLogic(logic, () => logic.actions.loadRecentReviews())
            .toDispatchActions(['loadRecentReviewsFailure'])
            .toNotHaveDispatchedActions(['markInitialLoadFailed'])
        expect(logic.values.initialLoadFailed).toBe(false)
    })

    it('flags a reviews failure with nothing loaded yet as an initial-load failure', async () => {
        // Without this the section sits on skeletons forever with no retry path offered.
        useMocks({ get: { '/api/projects/:team_id/review_hog/reviews/': () => [500, {}] } })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadRecentReviewsFailure', 'markInitialLoadFailed'])
        expect(logic.values.initialLoadFailed).toBe(true)
    })

    it('checks the list immediately when the tab becomes visible again', async () => {
        // The poll interval is paused while hidden and resumes with a full interval still to wait,
        // which reads as stale exactly when the user comes back to look.
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadRecentReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadRecentReviewsSuccess',
        ])

        await expectLogic(logic, () => {
            document.dispatchEvent(new Event('visibilitychange'))
        }).toDispatchActions(['loadRecentReviews'])
    })

    test.each([
        // Cross-kind adoption must strip the source's own prefix, or the copy gets a double-prefixed name.
        ['review-hog-validation-strict', 'resolution' as const, 'strict'],
        ['api-design-guidelines', 'perspective' as const, 'api-design-guidelines'],
        // Truncation to the 64-char cap must not leave a trailing hyphen, which the server rejects.
        ['a'.repeat(40) + '-' + 'b'.repeat(23), 'perspective' as const, 'a'.repeat(40)],
    ])('prefills the adopt slug from %s for kind %s', (sourceName, kind, expected) => {
        expect(defaultAdoptSlug(sourceName, kind)).toBe(expected)
    })

    test.each([
        ['', 'Enter a name for the copy'],
        ['Has-Uppercase', 'Use lowercase letters, numbers, and single hyphens between words'],
        ['double--hyphen', 'Use lowercase letters, numbers, and single hyphens between words'],
        ['trailing-', 'Use lowercase letters, numbers, and single hyphens between words'],
        ['a'.repeat(60), 'The full name must be 64 characters or fewer'],
        ['taken', 'A skill with this name already exists'],
        ['fine-name', null],
    ])('validates the adopt slug %s', (slug, expectedError) => {
        const taken = new Set(['review-hog-perspective-taken'])
        expect(validateAdoptSlug(slug, 'perspective', taken)).toBe(expectedError)
    })

    it('groups adoptable skills into teammates-of-the-kind and the rest of the store', async () => {
        // Guards the picker's filters: the user's own cards must not reappear as adoptable, a
        // teammate's same-kind custom must surface (it is invisible in the cards by design), and
        // other-kind review skills stay offered as plain store skills.
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/perspectives/': () => [
                    200,
                    [
                        {
                            skill_name: 'review-hog-perspective-logic-correctness',
                            enabled: true,
                            description: '',
                            body: '',
                        },
                    ],
                ],
                '/api/projects/:team_id/llm_skills/': () => [
                    200,
                    {
                        count: 4,
                        results: [
                            { name: 'review-hog-perspective-security-focus', description: 'A teammate lens' },
                            { name: 'review-hog-perspective-logic-correctness', description: 'Already a card' },
                            { name: 'review-hog-validation-strict', description: 'Another kind' },
                            { name: 'api-design-guidelines', description: 'Plain store skill' },
                        ],
                    },
                ],
            },
        })
        logic.mount()
        // Sequenced (perspectives settle before the modal opens) because the history pointer only
        // moves forward: racing the two fetches makes their success order nondeterministic.
        await expectLogic(logic).toDispatchActions(['loadPerspectivesSuccess'])
        logic.actions.openAdoptSkillModal('perspective')
        await expectLogic(logic).toDispatchActions(['loadAdoptableSkillsSuccess'])

        expect(logic.values.adoptSkillGroups).toEqual([
            {
                key: 'teammates',
                label: 'Perspectives from your teammates',
                skills: [{ name: 'review-hog-perspective-security-focus', description: 'A teammate lens' }],
            },
            {
                key: 'store',
                label: 'All team skills',
                skills: [
                    { name: 'review-hog-validation-strict', description: 'Another kind' },
                    { name: 'api-design-guidelines', description: 'Plain store skill' },
                ],
            },
        ])
    })

    test.each([
        ['perspective' as const, '/review_hog/perspectives/', { enabled: true }],
        ['validator' as const, '/review_hog/validators/', { active: true }],
    ])('adopting a skill as %s copies it under the prefix and switches it on', async (kind, patchPath, patchBody) => {
        // Guards the kind→endpoint mapping end to end: the duplicate must target the picked source
        // with the prefixed name, and the follow-up activation must hit the right kind's endpoint
        // with its cardinality's body (multi-toggle enabled vs single-active active).
        const duplicated: { source: string; body: Record<string, unknown> }[] = []
        const patched: { url: string; body: Record<string, unknown> }[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/llm_skills/': () => [
                    200,
                    { count: 1, results: [{ name: 'api-design-guidelines', description: '' }] },
                ],
            },
            post: {
                '/api/projects/:team_id/llm_skills/name/:skill_name/duplicate/': async ({ request, params }) => {
                    duplicated.push({
                        source: String(params.skill_name),
                        body: (await request.json()) as Record<string, unknown>,
                    })
                    return [201, { name: 'created' }]
                },
            },
            patch: {
                '/api/projects/:team_id/review_hog/perspectives/:skill_name/': async ({ request }) => {
                    patched.push({ url: request.url, body: (await request.json()) as Record<string, unknown> })
                    return [200, {}]
                },
                '/api/projects/:team_id/review_hog/validators/:skill_name/': async ({ request }) => {
                    patched.push({ url: request.url, body: (await request.json()) as Record<string, unknown> })
                    return [200, {}]
                },
            },
        })
        logic.mount()
        logic.actions.openAdoptSkillModal(kind)
        await expectLogic(logic).toDispatchActions(['loadAdoptableSkillsSuccess'])
        logic.actions.chooseAdoptSource({ name: 'api-design-guidelines', description: '' })

        const expectedName = `${REVIEW_SKILL_PREFIX_BY_KIND[kind]}api-design-guidelines`
        await expectLogic(logic, () => logic.actions.submitAdoptSkill())
            .toDispatchActions(['submitAdoptSkillStarted', 'submitAdoptSkillFinished', 'closeAdoptSkillModal'])
            .toMatchValues({ adoptingSkill: false, adoptSkillKind: null })
        expect(duplicated).toEqual([{ source: 'api-design-guidelines', body: { new_name: expectedName } }])
        expect(patched).toHaveLength(1)
        expect(patched[0].url).toContain(`${patchPath}${expectedName}/`)
        expect(patched[0].body).toEqual(patchBody)
    })

    it('a failed copy keeps the adopt modal open for a fix', async () => {
        // A name conflict must be correctable in place — closing the modal would throw away the
        // picked source, and firing the activation PATCH would target a skill that never got created.
        let patchCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/llm_skills/': () => [
                    200,
                    { count: 1, results: [{ name: 'api-design-guidelines', description: '' }] },
                ],
            },
            post: {
                '/api/projects/:team_id/llm_skills/name/:skill_name/duplicate/': () => [
                    400,
                    { attr: 'new_name', detail: 'A skill with this name already exists.' },
                ],
            },
            patch: {
                '/api/projects/:team_id/review_hog/perspectives/:skill_name/': () => {
                    patchCalls++
                    return [200, {}]
                },
            },
        })
        logic.mount()
        logic.actions.openAdoptSkillModal('perspective')
        await expectLogic(logic).toDispatchActions(['loadAdoptableSkillsSuccess'])
        logic.actions.chooseAdoptSource({ name: 'api-design-guidelines', description: '' })

        await expectLogic(logic, () => logic.actions.submitAdoptSkill())
            .toDispatchActions(['submitAdoptSkillStarted', 'submitAdoptSkillFinished'])
            .toNotHaveDispatchedActions(['closeAdoptSkillModal'])
            .toMatchValues({ adoptingSkill: false, adoptSkillKind: 'perspective' })
        expect(logic.values.adoptSource).toEqual({ name: 'api-design-guidelines', description: '' })
        expect(patchCalls).toBe(0)
    })

    it('a copy that cannot be switched on still surfaces its card', async () => {
        // The copy exists on the server even when activation fails, so the flow must reload the
        // kind's list (the card appears, off) and close, not strand the modal as if nothing happened.
        useMocks({
            get: {
                '/api/projects/:team_id/llm_skills/': () => [
                    200,
                    { count: 1, results: [{ name: 'api-design-guidelines', description: '' }] },
                ],
            },
            post: {
                '/api/projects/:team_id/llm_skills/name/:skill_name/duplicate/': () => [201, { name: 'created' }],
            },
            patch: {
                '/api/projects/:team_id/review_hog/perspectives/:skill_name/': () => [500, {}],
            },
        })
        logic.mount()
        logic.actions.openAdoptSkillModal('perspective')
        await expectLogic(logic).toDispatchActions(['loadAdoptableSkillsSuccess'])
        logic.actions.chooseAdoptSource({ name: 'api-design-guidelines', description: '' })

        await expectLogic(logic, () => logic.actions.submitAdoptSkill()).toDispatchActions([
            'submitAdoptSkillStarted',
            'loadPerspectives',
            'submitAdoptSkillFinished',
            'closeAdoptSkillModal',
        ])
    })

    it('loads every skills page so skills beyond the first stay adoptable', async () => {
        // The picker's search, grouping, and name-collision checks assume the complete store — a
        // loader that stops at one page would silently hide older skills and miss name conflicts.
        useMocks({
            get: {
                '/api/projects/:team_id/llm_skills/': ({ request }) => {
                    const offset = Number(new URL(request.url).searchParams.get('offset') ?? 0)
                    const pages: Record<number, { name: string; description: string }[]> = {
                        0: [{ name: 'newest-skill', description: '' }],
                        1: [{ name: 'older-skill', description: '' }],
                    }
                    return [
                        200,
                        {
                            count: 2,
                            results: pages[offset] ?? [],
                            next: offset === 0 ? '/api/projects/997/llm_skills/?offset=1' : null,
                        },
                    ]
                },
            },
        })
        logic.mount()
        logic.actions.openAdoptSkillModal('perspective')

        await expectLogic(logic).toDispatchActions(['loadAdoptableSkillsSuccess'])
        expect(logic.values.adoptableSkills?.map((skill) => skill.name)).toEqual(['newest-skill', 'older-skill'])
    })
})
