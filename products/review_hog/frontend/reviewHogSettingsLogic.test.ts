import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ReviewHogReviewsListScope } from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogSettingsLogic } from './reviewHogSettingsLogic'

describe('reviewHogSettingsLogic', () => {
    let logic: ReturnType<typeof reviewHogSettingsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                // The user has no reviews of their own; the project has one.
                '/api/projects/:team_id/review_hog/reviews/': ({ request }) => [
                    200,
                    new URL(request.url).searchParams.get('scope') === ReviewHogReviewsListScope.Everyone
                        ? [{ id: 'r1', in_progress: false }]
                        : [],
                ],
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
        expect(logic.values.recentReviews).toHaveLength(1)
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
})
