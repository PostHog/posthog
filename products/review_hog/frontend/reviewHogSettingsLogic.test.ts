import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ReviewHogReviewsListScope } from 'products/review_hog/frontend/generated/api.schemas'

import { MAX_REVIEWS_LIMIT, REVIEWS_PAGE_SIZE, reviewHogSettingsLogic } from './reviewHogSettingsLogic'

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
                    { review_inbox_prs: false, review_labeled_prs: true, urgency_threshold: 'should_fix' },
                ],
                '/api/projects/:team_id/review_hog/perspectives/': () => [200, []],
                '/api/projects/:team_id/review_hog/blind_spots/': () => [200, []],
                '/api/projects/:team_id/review_hog/validators/': () => [200, []],
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
})
