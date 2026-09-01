import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    RecurrenceIntervalEnumApi,
    ResourceTypeEnumApi,
    SubscriptionsDeliveriesListStatus,
    TargetTypeEnumApi,
} from 'products/subscriptions/frontend/generated/api.schemas'
import type { PulseRunHistoryDTOApi, SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { NEGATIVE_FEEDBACK_SURVEY_ID, subscriptionSceneLogic } from './subscriptionSceneLogic'

const MOCK_USER = {
    id: 1,
    uuid: '01863799-062b-0000-8a61-b2842d5f8642',
    email: 'test@posthog.com',
    first_name: 'Test',
    last_name: 'User',
    hedgehog_config: null,
} as const

const MOCK_SUBSCRIPTION: SubscriptionApi = {
    id: 1,
    resource_type: ResourceTypeEnumApi.Insight,
    insight: 101,
    dashboard: null,
    insight_short_id: 'abc123',
    resource_name: 'North star metric',
    contexts: [],
    proactive_config: {
        enabled: false,
        repository: null,
        repository_integration_id: null,
        create_draft_pr: false,
        repository_grant_id: null,
        public_research_enabled: true,
    },
    title: 'Weekly rollup',
    dashboard_export_insights: [],
    target_type: TargetTypeEnumApi.Email,
    target_value: 'a@b.com',
    frequency: RecurrenceIntervalEnumApi.Weekly,
    interval: 1,
    start_date: '2022-01-01T00:00:00Z',
    created_at: '2023-04-27T10:04:37.977401Z',
    created_by: MOCK_USER,
    summary: 'sent every week',
    next_delivery_date: '2026-04-07T17:00:00Z',
    deleted: false,
}

const MOCK_AI_SUBSCRIPTION: SubscriptionApi = {
    id: 2,
    resource_type: ResourceTypeEnumApi.AiPrompt,
    insight: null,
    dashboard: null,
    insight_short_id: null,
    resource_name: null,
    contexts: [],
    proactive_config: {
        enabled: false,
        repository: null,
        repository_integration_id: null,
        create_draft_pr: false,
        repository_grant_id: null,
        public_research_enabled: true,
    },
    prompt: 'Summarize weekly signups and flag any anomalies',
    title: 'Weekly AI digest',
    dashboard_export_insights: [],
    target_type: TargetTypeEnumApi.Email,
    target_value: 'a@b.com',
    frequency: RecurrenceIntervalEnumApi.Weekly,
    interval: 1,
    start_date: '2022-01-01T00:00:00Z',
    created_at: '2023-04-27T10:04:37.977401Z',
    created_by: MOCK_USER,
    summary: 'sent every week',
    next_delivery_date: '2026-04-07T17:00:00Z',
    deleted: false,
}

describe('subscriptionSceneLogic', () => {
    let deliveriesRequestUrls: string[]
    let pulseHistoryRequestUrls: string[]

    beforeEach(() => {
        deliveriesRequestUrls = []
        pulseHistoryRequestUrls = []
        // deliveryFeedback persists to localStorage; clear it so recorded feedback can't leak between tests.
        localStorage.clear()
    })

    it('includes status in deliveries list request when status filter is set', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/environments/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: ({ request }) => {
                    deliveriesRequestUrls.push(request.url)
                    return [200, { results: [], next: null, previous: null }]
                },
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: ({ request }) => {
                    deliveriesRequestUrls.push(request.url)
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(deliveriesRequestUrls).toHaveLength(1)
        expect(deliveriesRequestUrls[0]).not.toContain('status=')

        await expectLogic(logic, () => {
            logic.actions.setDeliveryStatusFilter(SubscriptionsDeliveriesListStatus.Failed)
        }).toFinishAllListeners()

        expect(deliveriesRequestUrls).toHaveLength(2)
        expect(deliveriesRequestUrls[1]).toContain('status=failed')
        logic.unmount()
    })

    it('loads delivery history once the subscription has loaded', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: () => {
                    deliveriesRequestUrls.push('deliveries')
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(deliveriesRequestUrls).toHaveLength(1)
        logic.unmount()
    })

    it.each([
        [403, true],
        [404, false],
    ])('marks only a %s subscription load failure as access denied', async (status, subscriptionAccessDenied) => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: () => [status, { detail: 'Request failed' }],
            },
        })
        initKeaTests()
        const logic = subscriptionSceneLogic({ id: '1' })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadSubscriptionFailure'])
            .toMatchValues({ subscriptionAccessDenied })

        logic.unmount()
    })

    // The failure path matters too: the header button's double-submit guard would stick
    // if deliveringSubscriptionId reset only on success.
    it.each([
        { name: 'success', status: 202, terminalAction: 'deliverSubscriptionSuccess' },
        { name: 'failure', status: 500, terminalAction: 'deliverSubscriptionFailure' },
    ])('test delivery ($name) flips deliveringSubscriptionId then resets it', async ({ status, terminalAction }) => {
        let testDeliveryCalls = 0
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: [
                    200,
                    { results: [], next: null, previous: null },
                ],
            },
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/test-delivery/`]: () => {
                    testDeliveryCalls += 1
                    return [status, {}]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.deliverSubscription(1)
        }).toMatchValues({ deliveringSubscriptionId: 1 })

        await expectLogic(logic).toDispatchActions([terminalAction]).toMatchValues({
            deliveringSubscriptionId: null,
        })
        expect(testDeliveryCalls).toEqual(1)
        logic.unmount()
    })

    it('loads an AI prompt subscription and its deliveries', async () => {
        useMocks({
            get: {
                // Function form, not the `[200, body]` shorthand: useMocks serializes a bare array as
                // the whole response body, so only a function-returned tuple delivers the object itself.
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/deliveries/`]: () => {
                    deliveriesRequestUrls.push('deliveries')
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.subscription?.resource_type).toEqual(ResourceTypeEnumApi.AiPrompt)
        expect(logic.values.subscription?.prompt).toBeTruthy()
        expect(deliveriesRequestUrls).toHaveLength(1)
        logic.unmount()
    })

    it('loads bounded Pulse history for an AI prompt subscription', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/deliveries/`]: () => [
                    200,
                    { results: [], next: null, previous: null },
                ],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/pulse/history/`]: ({ request }) => {
                    pulseHistoryRequestUrls.push(request.url)
                    return [200, []]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(pulseHistoryRequestUrls).toHaveLength(1)
        expect(pulseHistoryRequestUrls[0]).toContain('subscription_id=2')
        logic.unmount()
    })

    it('marks Pulse history unavailable when its request fails', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/deliveries/`]: () => [
                    200,
                    { results: [], next: null, previous: null },
                ],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/pulse/history/`]: () => [500, { detail: 'Unavailable' }],
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pulseHistoryLoadFailed).toBe(true)
        logic.unmount()
    })

    it('persists a Pulse decision once, updates every history copy, and refreshes the server-owned result', async () => {
        const actionId = '00000000-0000-4000-8000-000000000003'
        const feedbackBodies: unknown[] = []
        const pulseHistory = (): PulseRunHistoryDTOApi[] =>
            [
                {
                    id: '00000000-0000-4000-8000-000000000004',
                    subscription_id: 2,
                    delivery_id: '00000000-0000-4000-8000-000000000005',
                    status: 'completed',
                    started_at: '2026-08-30T10:00:00Z',
                    finished_at: '2026-08-30T10:01:00Z',
                    task_id: null,
                    analysis_task_run_id: null,
                    execution_task_run_id: null,
                    failure_code: null,
                    skip_reason: null,
                    deliveries: [],
                    actions: [
                        {
                            id: actionId,
                            action_key: 'recommendation-1',
                            kind: 'recommendation',
                            title: 'Review a conversion trend',
                            rationale: 'A conversion rate changed.',
                            expected_impact: 'Identify a regression.',
                            rank: 1,
                            implementation_selected: true,
                            status: 'completed',
                            evidence: [],
                            citations: [],
                            build_test_gate: null,
                            artifacts: [],
                        },
                    ],
                },
            ] as unknown as PulseRunHistoryDTOApi[]
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/deliveries/`]: () => [
                    200,
                    { results: [], next: null, previous: null },
                ],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/pulse/history/`]: ({ request }) => {
                    pulseHistoryRequestUrls.push(request.url)
                    return [200, pulseHistory()]
                },
            },
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/pulse/actions/${actionId}/decision/`]: async ({
                    request,
                }) => {
                    feedbackBodies.push(await request.json())
                    return [
                        200,
                        {
                            plan_id: '00000000-0000-4000-8000-000000000006',
                            action_id: actionId,
                            adoption_status: 'adopted',
                            readout_status: 'scheduled',
                            adopted_at: '2026-08-30T10:02:00Z',
                            decision_at: '2026-08-30T10:02:00Z',
                            decided_by_id: 1,
                            next_readout_at: '2026-09-06T10:02:00Z',
                        },
                    ]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.decidePulseAction(actionId, 'adopted')
            logic.actions.decidePulseAction(actionId, 'adopted')
        }).toFinishAllListeners()

        expect(feedbackBodies).toEqual([{ decision: 'adopted' }])
        expect(pulseHistoryRequestUrls).toHaveLength(2)
        expect(logic.values.pulseDecisionLoadingIds).toEqual({})
        logic.unmount()
    })

    it('clears a failed Pulse decision and tells the person how to retry', async () => {
        const actionId = '00000000-0000-4000-8000-000000000003'
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/deliveries/`]: () => [
                    200,
                    { results: [], next: null, previous: null },
                ],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/pulse/history/`]: () => [200, []],
            },
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/pulse/actions/${actionId}/decision/`]: () => [500, {}],
            },
        })
        initKeaTests()
        const toastSpy = jest.spyOn(lemonToast, 'error')
        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.decidePulseAction(actionId, 'dismissed')
        }).toFinishAllListeners()

        expect(logic.values.pulseDecisionLoadingIds).toEqual({})
        expect(toastSpy).toHaveBeenCalledWith('Could not update this recommendation. Try again.')
        toastSpy.mockRestore()
        logic.unmount()
    })

    it.each([
        ['positive' as const, 'email'],
        ['negative' as const, 'slack'],
    ])('captures ai_report_feedback (%s, %s) from URL params and strips them', async (feedback, source) => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
            },
        })
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')
        const displaySurveySpy = jest.spyOn(posthog, 'displaySurvey')

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic, () => {
            router.actions.push('/subscriptions/2', {
                feedback_delivery: 'd-123',
                feedback,
                feedback_source: source,
            })
        }).toFinishAllListeners()

        expect(captureSpy).toHaveBeenCalledWith('ai_report_feedback', {
            subscription_id: 2,
            delivery_id: 'd-123',
            feedback,
            source,
            previous_feedback: null,
        })
        // The "what was wrong?" survey opens only on a downvote, and this Slack/email flow must
        // show it before the redirect strips the feedback params.
        const expectedSurveyCalls = feedback === 'negative' ? [[NEGATIVE_FEEDBACK_SURVEY_ID]] : []
        expect(displaySurveySpy.mock.calls).toEqual(expectedSurveyCalls)
        // A feedback landing is also a click-through on the delivered report.
        expect(captureSpy).toHaveBeenCalledWith('ai_report_clicked', {
            subscription_id: 2,
            delivery_id: 'd-123',
            link: 'feedback',
            source,
        })
        // The replace must remove the params so a refresh doesn't double-capture.
        expect(router.values.searchParams).toEqual({})
        expect(captureSpy.mock.calls.filter(([event]) => event === 'ai_report_feedback')).toHaveLength(1)

        logic.unmount()
        captureSpy.mockRestore()
        displaySurveySpy.mockRestore()
    })

    it('captures ai_report_clicked from the report CTA delivery param and strips it', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
            },
        })
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic, () => {
            router.actions.push('/subscriptions/2', { delivery: 'd-123', utm_medium: 'email' })
        }).toFinishAllListeners()

        expect(captureSpy).toHaveBeenCalledWith('ai_report_clicked', {
            subscription_id: 2,
            delivery_id: 'd-123',
            link: 'manage',
            source: 'email',
        })
        expect(captureSpy.mock.calls.filter(([event]) => event === 'ai_report_feedback')).toHaveLength(0)
        // Only the delivery param is consumed — utm params stay for posthog-js.
        expect(router.values.searchParams).toEqual({ utm_medium: 'email' })

        logic.unmount()
        captureSpy.mockRestore()
    })

    it('does not re-capture from a feedback link for an already-recorded delivery', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
            },
        })
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')
        const displaySurveySpy = jest.spyOn(posthog, 'displaySurvey')

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.submitDeliveryFeedback('d-123', 'positive', 'in_app')
        }).toFinishAllListeners()
        captureSpy.mockClear()

        await expectLogic(logic, () => {
            router.actions.push('/subscriptions/2', {
                feedback_delivery: 'd-123',
                feedback: 'negative',
                feedback_source: 'email',
            })
        }).toFinishAllListeners()

        expect(captureSpy.mock.calls.filter(([event]) => event === 'ai_report_feedback')).toHaveLength(0)
        // The already-recorded delivery is skipped, so the survey isn't reshown on a re-click either.
        expect(displaySurveySpy).not.toHaveBeenCalled()
        // Params are still stripped, and the originally recorded feedback wins.
        expect(router.values.searchParams).toEqual({})
        expect(logic.values.deliveryFeedback).toEqual({ 'd-123': 'positive' })

        logic.unmount()
        captureSpy.mockRestore()
        displaySurveySpy.mockRestore()
    })

    it('persists recorded feedback across remounts', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
            },
        })
        initKeaTests()

        let logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.submitDeliveryFeedback('d-9', 'positive', 'in_app')
        }).toFinishAllListeners()
        logic.unmount()

        logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        expect(logic.values.deliveryFeedback).toEqual({ 'd-9': 'positive' })
        // The thanks flash is transient — after a remount the row goes straight to the recorded option.
        expect(logic.values.recentlyThankedDeliveries).toEqual({})

        logic.unmount()
    })

    it('captures in-app thumbs feedback and records it per delivery', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
            },
        })
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')
        const displaySurveySpy = jest.spyOn(posthog, 'displaySurvey')

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.submitDeliveryFeedback('d-9', 'negative', 'in_app')
        }).toFinishAllListeners()

        expect(captureSpy).toHaveBeenCalledWith('ai_report_feedback', {
            subscription_id: 2,
            delivery_id: 'd-9',
            feedback: 'negative',
            source: 'in_app',
            previous_feedback: null,
        })
        // Downvoting from the in-app thumbs opens the follow-up survey too.
        expect(displaySurveySpy).toHaveBeenCalledWith(NEGATIVE_FEEDBACK_SURVEY_ID)
        expect(logic.values.deliveryFeedback).toEqual({ 'd-9': 'negative' })
        // Thanks flashes first, then expiry settles the row into the recorded option.
        expect(logic.values.recentlyThankedDeliveries).toEqual({ 'd-9': true })
        await expectLogic(logic, () => {
            logic.actions.expireDeliveryThanks('d-9')
        }).toFinishAllListeners()
        expect(logic.values.recentlyThankedDeliveries).toEqual({})
        expect(logic.values.deliveryFeedback).toEqual({ 'd-9': 'negative' })

        // Switching the vote captures again with the previous value, and the latest one wins.
        await expectLogic(logic, () => {
            logic.actions.submitDeliveryFeedback('d-9', 'positive', 'in_app')
        }).toFinishAllListeners()
        expect(captureSpy).toHaveBeenCalledWith('ai_report_feedback', {
            subscription_id: 2,
            delivery_id: 'd-9',
            feedback: 'positive',
            source: 'in_app',
            previous_feedback: 'negative',
        })
        expect(logic.values.deliveryFeedback).toEqual({ 'd-9': 'positive' })
        // Switching to a positive vote must not reopen the survey.
        expect(displaySurveySpy).toHaveBeenCalledTimes(1)

        logic.unmount()
        captureSpy.mockRestore()
        displaySurveySpy.mockRestore()
    })
})
