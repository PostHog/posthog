import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ReviewHogReviewsListScope } from 'products/review_hog/frontend/generated/api.schemas'

import { REVIEWS_PAGE_SIZE, reviewHogSettingsLogic } from './reviewHogSettingsLogic'

// More project-wide reviews than two pages, so "Show more" always has something to reveal.
const everyoneReviews = Array.from({ length: 12 }, (_, i) => ({ id: `r${i}`, in_progress: false }))

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
})
