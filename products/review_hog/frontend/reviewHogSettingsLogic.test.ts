import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    ReviewHogReviewsListScope,
    type ReviewReviewsTablePageApi,
    ReviewTriggerRequestRunModeEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import {
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

// More project-wide reviews than one page, so paging is reachable.
const everyoneReviews = Array.from({ length: REVIEWS_PAGE_SIZE * 2 + 3 }, (_, i) => ({
    id: `r${i}`,
    repository: 'example-org/example-repo',
    in_progress: false,
    run_count: 1,
}))

describe('reviewHogSettingsLogic', () => {
    let logic: ReturnType<typeof reviewHogSettingsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                // The user has no reviews of their own; the project has a few pages.
                '/api/projects/:team_id/review_hog/reviews/table/': ({ request }) => {
                    const url = new URL(request.url)
                    const limit = Number(url.searchParams.get('limit'))
                    const offset = Number(url.searchParams.get('offset'))
                    const pool =
                        url.searchParams.get('scope') === ReviewHogReviewsListScope.Everyone ? everyoneReviews : []
                    return [200, { count: pool.length, running_count: 0, results: pool.slice(offset, offset + limit) }]
                },
                '/api/projects/:team_id/review_hog/reviews/perspective_stats/': () => [
                    200,
                    { report_count: 0, perspectives: [] },
                ],
                '/api/projects/:team_id/review_hog/settings/': () => [
                    200,
                    {
                        review_inbox_prs: false,
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
            .toDispatchActions(['loadReviewsSuccess', 'applyDefaultReviewsScope', 'loadReviewsSuccess'])
            .toMatchValues({
                reviewsScope: ReviewHogReviewsListScope.Everyone,
                // The auto-default is not an explicit choice — a later real one must still win.
                hasUserChosenReviewsScope: false,
            })
        expect(logic.values.reviews).toHaveLength(REVIEWS_PAGE_SIZE)
        // The auto-default must not write the URL: hydrating `?reviews_scope=` from a link marks
        // the scope as explicitly chosen, so mirroring the fallback would make it permanent.
        expect(router.values.searchParams.reviews_scope).toBeUndefined()
    })

    it('following the project default writes the project value, so the server drops the own value', async () => {
        const patches: Record<string, unknown>[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/settings/': () => [
                    200,
                    {
                        urgency_threshold: 'must_fix',
                        sources: { urgency_threshold: 'user' },
                        project_defaults: { urgency_threshold: 'should_fix', celebrate_clean_reviews: true },
                    },
                ],
            },
            patch: {
                '/api/projects/:team_id/review_hog/settings/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    patches.push(body)
                    return [
                        200,
                        {
                            urgency_threshold: 'should_fix',
                            sources: { urgency_threshold: 'project' },
                            project_defaults: { urgency_threshold: 'should_fix', celebrate_clean_reviews: true },
                        },
                    ]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSettingsSuccess'])

        await expectLogic(logic, () => logic.actions.followProjectDefault('urgency_threshold')).toDispatchActions([
            'updateSettings',
            'updateSettingsSuccess',
        ])

        expect(patches).toEqual([{ urgency_threshold: 'should_fix' }])
        expect(logic.values.settings?.sources.urgency_threshold).toBe('project')
    })

    it('a started review clears the input, reloads the list, and resets the in-flight flag', async () => {
        logic.mount()
        // Consume the mount-time auto-default so its loadReviews can't satisfy the assertion below.
        await expectLogic(logic).toDispatchActions([
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        await expectLogic(logic, () => logic.actions.submitTriggerReview())
            .toDispatchActions([
                'submitTriggerReview',
                'startTriggeredReviewWatch',
                'loadReviews',
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
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
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
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        await expectLogic(logic, () =>
            logic.actions.submitTriggerReview(ReviewTriggerRequestRunModeEnumApi.ResolveOnly)
        )
            .toDispatchActions(['submitTriggerReview', 'loadReviews', 'submitTriggerReviewFinished'])
            .toNotHaveDispatchedActions(['startTriggeredReviewWatch'])
            .toMatchValues({ triggeringReview: false, triggerPrUrl: '', awaitingTriggeredReview: false })
        expect(requestBody).toMatchObject({ run_mode: 'resolve_only' })
    })

    it('a flash run sends its mode and arms the review watch like a review', async () => {
        // Flash creates a report row like any review, so the watch must arm; dropping run_mode
        // would silently run the full pipeline (and resolve comments) under the flash button.
        let requestBody: Record<string, unknown> | null = null
        useMocks({
            post: {
                '/api/projects/:team_id/review_hog/reviews/trigger/': async ({ request }) => {
                    requestBody = (await request.json()) as Record<string, unknown>
                    return [202, { workflow_id: 'wf-flash-1', status: 'started' }]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        await expectLogic(logic, () => logic.actions.submitTriggerReview(ReviewTriggerRequestRunModeEnumApi.Flash))
            .toDispatchActions(['submitTriggerReview', 'startTriggeredReviewWatch', 'submitTriggerReviewFinished'])
            .toMatchValues({ triggeringReview: false, triggerPrUrl: '' })
        expect(requestBody).toMatchObject({ run_mode: 'flash' })
    })

    it.each([
        ['already_reviewed', 200, ''],
        ['joined_running_review', 202, 'wf-running'],
    ])('a %s response informs without arming the watch', async (status, code, workflowId) => {
        useMocks({
            post: {
                '/api/projects/:team_id/review_hog/reviews/trigger/': () => [code, { workflow_id: workflowId, status }],
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        await expectLogic(logic, () => logic.actions.submitTriggerReview())
            .toDispatchActions(['submitTriggerReview', 'loadReviews', 'submitTriggerReviewFinished'])
            .toNotHaveDispatchedActions(['startTriggeredReviewWatch'])
            .toMatchValues({ triggeringReview: false, triggerPrUrl: '', awaitingTriggeredReview: false })
    })

    it('a rejected trigger resets the in-flight flag and keeps the input for correction', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/review_hog/reviews/trigger/': () => [
                    403,
                    { error: "PostHog Review can't start reviews from this project yet" },
                ],
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
        ])
        logic.actions.setTriggerPrUrl('https://github.com/PostHog/posthog.com/pull/1')

        await expectLogic(logic, () => logic.actions.submitTriggerReview())
            .toDispatchActions(['submitTriggerReview', 'submitTriggerReviewFinished'])
            .toNotHaveDispatchedActions(['loadReviews', 'startTriggeredReviewWatch'])
            .toMatchValues({
                triggeringReview: false,
                triggerPrUrl: 'https://github.com/PostHog/posthog.com/pull/1',
                awaitingTriggeredReview: false,
            })
    })

    it('the scope switch rescopes the effectiveness stats along with the list, never the skill counts', async () => {
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
            .toDispatchActions(['loadReviewsSuccess', 'applyDefaultReviewsScope', 'loadReviewsSuccess'])
            .toFinishAllListeners()
        // The Settings tab's skill counts read the viewer's own Deep reviews, so the Activity switch
        // must never reload or rescope them.
        const ownDeepLoads = statsScopes.filter((scope) => scope === 'own_deep').length
        expect(ownDeepLoads).toBe(1)
        const listScopes = (): (string | null)[] => statsScopes.filter((scope) => scope !== 'own_deep')
        // The mount-time auto-default to Entire project already rescoped the stats.
        expect(listScopes()[listScopes().length - 1]).toBe(ReviewHogReviewsListScope.Everyone)

        logic.actions.setReviewsScope(ReviewHogReviewsListScope.Mine)
        // Old data drops synchronously so neither the cards nor the list ever show the other
        // scope's content — even if the reload were to fail.
        expect(logic.values.perspectiveStats).toBeNull()
        expect(logic.values.reviews).toBeNull()
        await expectLogic(logic).toDispatchActions(['loadPerspectiveStatsSuccess'])
        expect(listScopes()[listScopes().length - 1]).toBe(ReviewHogReviewsListScope.Mine)
        expect(statsScopes.filter((scope) => scope === 'own_deep')).toHaveLength(ownDeepLoads)
    })

    it('respects an explicit scope choice even when that scope is empty', async () => {
        logic.mount()
        // Consume the mount-time auto-default, so the not-dispatched window below starts after it.
        await expectLogic(logic).toDispatchActions([
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
        ])

        await expectLogic(logic, () => logic.actions.setReviewsScope(ReviewHogReviewsListScope.Mine))
            .toDispatchActions(['loadReviewsSuccess'])
            .toNotHaveDispatchedActions(['applyDefaultReviewsScope'])
            .toMatchValues({
                reviewsScope: ReviewHogReviewsListScope.Mine,
                hasUserChosenReviewsScope: true,
                reviews: [],
            })
    })

    it('a filter change resets the page and sends the filter with the request', async () => {
        // Page 2 of every review is rarely a page at all once a filter narrows the set; a kept page
        // number would land the reader on an empty table.
        const requests: URLSearchParams[] = []
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
        ])
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/reviews/table/': ({ request }) => {
                    requests.push(new URL(request.url).searchParams)
                    return [200, { count: 0, running_count: 0, results: [] }]
                },
            },
        })

        await expectLogic(logic, () => logic.actions.setReviewsPage(2)).toDispatchActions(['loadReviewsSuccess'])
        expect(requests[requests.length - 1].get('offset')).toBe(String(REVIEWS_PAGE_SIZE))

        await expectLogic(logic, () => logic.actions.setReviewsRepository('example-org/example-repo'))
            .toDispatchActions(['loadReviewsSuccess'])
            .toMatchValues({ reviewsCurrentPage: 1 })
        expect(requests[requests.length - 1].get('offset')).toBe('0')
        expect(requests[requests.length - 1].get('repository')).toBe('example-org/example-repo')
        expect(router.values.searchParams.reviews_repository).toBe('example-org/example-repo')
        expect(router.values.searchParams.reviews_page).toBeUndefined()
    })

    it('restores filters and the page from a link without resetting the page', async () => {
        // Each filter setter resets the page, so an unguarded replay would drop every shared
        // `reviews_page` back to page 1.
        router.actions.push(urls.codeReview(), {
            reviews_scope: 'everyone',
            reviews_status: 'completed',
            reviews_published: 'false',
            reviews_page: '2',
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReviewsSuccess']).toMatchValues({
            reviewsStatus: 'completed',
            reviewsPublished: false,
            reviewsCurrentPage: 2,
        })
        expect(logic.values.reviews?.[0].id).toBe(`r${REVIEWS_PAGE_SIZE}`)
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
        await expectLogic(logic).toDispatchActions(['loadReviewsSuccess'])

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

    it('opens the tab from ?tab= and mirrors tab changes back to the URL', async () => {
        logic.mount()
        router.actions.push(urls.codeReview(), { tab: 'settings' })
        expect(logic.values.activeTab).toBe('settings')

        // Activity is the default, so it keeps the URL clean; other params survive the write.
        router.actions.push(urls.codeReview(), { tab: 'settings', reviews_scope: 'everyone' })
        logic.actions.setActiveTab('activity')
        expect(router.values.searchParams.tab).toBeUndefined()
        expect(router.values.searchParams.reviews_scope).toBe('everyone')

        logic.actions.setActiveTab('settings')
        expect(router.values.searchParams.tab).toBe('settings')
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
        await expectLogic(logic).toDispatchActions(['loadReviewsSuccess'])

        router.actions.push(urls.codeReview(), { review: 'r-gone' })
        await expectLogic(logic).toDispatchActions([
            'openReviewDetailById',
            'loadReviewDetailFailure',
            'closeReviewDrawer',
        ])
        expect(logic.values.reviewDrawerOpen).toBe(false)
        expect(router.values.searchParams.review).toBeUndefined()
    })

    it('polls only while the page has a running review', async () => {
        // A poll that never stops spends a request every 10s on an idle table; one that never
        // starts leaves a running row's stage frozen.
        const page = (inProgress: boolean): ReviewReviewsTablePageApi =>
            ({
                count: 1,
                running_count: inProgress ? 1 : 0,
                results: [
                    { id: 'r-live', repository: 'example-org/example-repo', in_progress: inProgress, run_count: 1 },
                ],
            }) as ReviewReviewsTablePageApi
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadReviewsSuccess', 'applyDefaultReviewsScope', 'loadReviewsSuccess'])
            .toFinishAllListeners()
        jest.useFakeTimers()
        try {
            logic.actions.loadReviewsSuccess(page(true))
            await expectLogic(logic, () => {
                jest.advanceTimersByTime(10_000)
            }).toDispatchActions(['loadReviews'])

            logic.actions.loadReviewsSuccess(page(false))
            await expectLogic(logic, () => {
                jest.advanceTimersByTime(60_000)
            }).toNotHaveDispatchedActions(['loadReviews'])
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([
        ['stays on the page', false],
        ['leaves a Running filter', true],
    ])('refreshes the stats and an open drawer when a watched run finishes and %s', async (_, leavesPage) => {
        // A poll response is the only place a completion becomes visible: without the fan-out the
        // proof/effectiveness cards and an open drawer keep pre-completion numbers until reload.
        let finished = false
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/reviews/table/': () => [
                    200,
                    {
                        count: finished && leavesPage ? 0 : 1,
                        running_count: finished ? 0 : 1,
                        results:
                            finished && leavesPage
                                ? []
                                : [
                                      {
                                          id: 'r-live',
                                          repository: 'example-org/example-repo',
                                          in_progress: !finished,
                                          run_count: finished ? 1 : 0,
                                      },
                                  ],
                    },
                ],
                '/api/projects/:team_id/review_hog/reviews/r-live/': () => [200, reviewDetail('r-live', null)],
            },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReviewsSuccess']).toFinishAllListeners()

        logic.actions.openReviewDetailById('r-live')
        await expectLogic(logic).toDispatchActions(['loadReviewDetailSuccess'])

        finished = true
        await expectLogic(logic, () => logic.actions.loadReviews()).toDispatchActions([
            'loadReviewsSuccess',
            'loadPerspectiveStats',
            'loadReviewDetail',
        ])
    })

    it('keeps the rows on a background refresh blip and shows the error only with nothing loaded', async () => {
        // A poll blip must not replace rows on screen with an error, and a first load that fails
        // must not read as an empty table.
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
        ])
        useMocks({ get: { '/api/projects/:team_id/review_hog/reviews/table/': () => [500, {}] } })

        await expectLogic(logic, () => logic.actions.loadReviews()).toDispatchActions(['loadReviewsFailure'])
        expect(logic.values.reviews).toHaveLength(REVIEWS_PAGE_SIZE)

        await expectLogic(logic, () => logic.actions.setReviewsPage(2)).toDispatchActions(['loadReviewsFailure'])
        expect(logic.values).toMatchObject({ reviewsPage: null, reviewsFailed: true, initialLoadFailed: false })
    })

    it('checks the list immediately when the tab becomes visible again', async () => {
        // The poll interval is paused while hidden and resumes with a full interval still to wait,
        // which reads as stale exactly when the user comes back to look.
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadReviewsSuccess',
            'applyDefaultReviewsScope',
            'loadReviewsSuccess',
        ])

        await expectLogic(logic, () => {
            document.dispatchEvent(new Event('visibilitychange'))
        }).toDispatchActions(['loadReviews'])
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
