import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { getRecentSlackChannelIds } from 'lib/integrations/slackChannel'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId, SubscriptionType } from '~/types'

import { subscriptionLogic } from './subscriptionLogic'

jest.mock('posthog-js')

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const Insight1 = '1' as InsightShortId

export const fixtureSubscriptionResponse = (id: number, args: Partial<SubscriptionType> = {}): SubscriptionType =>
    ({
        id,
        title: 'My example subscription',
        target_type: 'email',
        target_value: 'ben@posthog.com,geoff@other-company.com',
        frequency: 'monthly',
        interval: 2,
        start_date: '2022-01-01T00:09:00',
        byweekday: ['wednesday'],
        bysetpos: 1,
        ...args,
    }) as SubscriptionType

describe('subscriptionLogic', () => {
    let newLogic: ReturnType<typeof subscriptionLogic.build>
    let existingLogic: ReturnType<typeof subscriptionLogic.build>
    beforeEach(async () => {
        jest.clearAllMocks()
        window.localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team/subscriptions': { count: 1, results: [fixtureSubscriptionResponse(1)] },
                '/api/environments/:team/subscriptions/1': fixtureSubscriptionResponse(1),
                '/api/projects/:team/subscriptions/1/deliveries/': {
                    next: null,
                    previous: null,
                    results: [],
                },
                '/api/projects/:team/integrations': { count: 0, results: [] },
                '/api/environments/:team/subscriptions/summary_quota': {
                    active_count: 0,
                    limit: null,
                    at_limit: false,
                },
            },
            post: {
                '/api/environments/:team/subscriptions': async ({ request }) => [
                    200,
                    { id: 42, ...((await request.json()) as Partial<SubscriptionType>) } as SubscriptionType,
                ],
            },
        })
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        newLogic = subscriptionLogic({
            insightShortId: Insight1,
            id: 'new',
        })
        existingLogic = subscriptionLogic({
            insightShortId: Insight1,
            id: 1,
        })
        newLogic.mount()
        existingLogic.mount()
    })

    afterEach(() => {
        window.localStorage.clear()
    })

    it('loads existing subscription', async () => {
        router.actions.push('/insights/123/subscriptions/1')
        await expectLogic(existingLogic).toFinishListeners().toDispatchActions(['loadSubscriptionSuccess'])
        expect(existingLogic.values.subscription).toMatchObject({
            id: 1,
            title: 'My example subscription',
            target_type: 'email',
            target_value: 'ben@posthog.com,geoff@other-company.com',
            frequency: 'monthly',
            interval: 2,
            start_date: '2022-01-01T00:09:00',
            byweekday: ['wednesday'],
            bysetpos: 1,
            // write-only on the API, so the edit form defaults it on to match the create flow
            send_test_now: true,
        })
    })

    it('loads the latest delivery for the current subscription', async () => {
        useMocks({
            get: {
                '/api/projects/:team/subscriptions/1/deliveries/': {
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 'delivery-1',
                            created_at: '2026-08-06T13:00:00Z',
                            finished_at: '2026-08-06T13:01:00Z',
                        },
                    ],
                },
            },
        })

        router.actions.push('/insights/123/subscriptions/1')
        await expectLogic(existingLogic).toFinishListeners().toDispatchActions(['loadLastDeliverySuccess'])

        expect(existingLogic.values.lastDelivery).toMatchObject({ id: 'delivery-1' })
    })

    it('uses the UTC weekday for legacy weekly subscriptions', async () => {
        useMocks({
            get: {
                '/api/environments/:team/subscriptions/1': fixtureSubscriptionResponse(1, {
                    frequency: 'weekly',
                    start_date: '2024-01-01T00:30:00Z',
                    byweekday: null,
                    bysetpos: null,
                }),
            },
        })

        router.actions.push('/insights/123/subscriptions/1')
        await expectLogic(existingLogic).toFinishListeners().toDispatchActions(['loadSubscriptionSuccess'])

        expect(existingLogic.values.subscription.byweekday).toEqual(['monday'])
    })

    it('removes hidden weekday constraints from daily subscriptions with intervals greater than one', async () => {
        useMocks({
            get: {
                '/api/environments/:team/subscriptions/1': fixtureSubscriptionResponse(1, {
                    frequency: 'daily',
                    interval: 2,
                    byweekday: ['monday', 'wednesday'],
                }),
            },
        })

        router.actions.push('/insights/123/subscriptions/1')
        await expectLogic(existingLogic).toFinishListeners().toDispatchActions(['loadSubscriptionSuccess'])

        expect(existingLogic.values.subscription.byweekday).toEqual([
            'monday',
            'tuesday',
            'wednesday',
            'thursday',
            'friday',
            'saturday',
            'sunday',
        ])
    })

    it('updates values depending on frequency', async () => {
        router.actions.push('/insights/123/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'weekly',
            bysetpos: null,
            byweekday: ['monday'],
        })
        // A plain "new subscription" open (no prefill) must not pre-mark the form as changed,
        // otherwise "Create subscription" would be enabled before the user has done anything.
        expect(newLogic.values.subscriptionChanged).toBe(false)

        newLogic.actions.setSubscriptionValue('frequency', 'daily')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'daily',
            bysetpos: null,
            byweekday: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
        })

        newLogic.actions.setSubscriptionValue('interval', 2)
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription.byweekday).toEqual([
            'monday',
            'tuesday',
            'wednesday',
            'thursday',
            'friday',
            'saturday',
            'sunday',
        ])

        newLogic.actions.setSubscriptionValues({
            interval: 7,
            start_date: '2024-01-01T09:00:00Z',
            byweekday: ['tuesday'],
        })
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscriptionErrors.frequency).toBe(
            'Select the delivery day matching the start date for this interval'
        )

        newLogic.actions.setSubscriptionValue('byweekday', [])
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscriptionErrors.frequency).toBe('Select at least one delivery day')

        newLogic.actions.setSubscriptionValue('frequency', 'weekly')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'weekly',
            bysetpos: null,
            byweekday: ['monday'],
        })

        newLogic.actions.setSubscriptionValue('frequency', 'monthly')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'monthly',
            bysetpos: 1,
            byweekday: ['monday'],
        })
    })

    it('preselects an AI prompt report from the new-subscription URL', async () => {
        router.actions.push('/insights/123/subscriptions/new?resource_type=ai_prompt')

        await expectLogic(newLogic).toFinishListeners()

        expect(newLogic.values.subscription.resource_type).toBe('ai_prompt')
    })

    it('sets the type from query params', async () => {
        router.actions.push('/insights/123/subscriptions/new?target_type=slack')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            target_type: 'slack',
        })
    })

    // Products deep-link here with a ready-made report (the MCP analytics recurring-report cards),
    // so dropping this prefill would silently open an empty form and lose the whole one-click flow.
    it('prefills a ready-made AI report from the parent-less new-subscription URL', async () => {
        const promptLogic = subscriptionLogic({ id: 'new' })
        promptLogic.mount()

        router.actions.push(
            '/subscriptions/new?resource_type=ai_prompt&prompt=Rank%20what%20agents%20asked%20for&title=MCP%20intent%20roundup&frequency=weekly&target_type=slack'
        )
        await expectLogic(promptLogic).toFinishListeners()

        expect(promptLogic.values.subscription).toMatchObject({
            resource_type: 'ai_prompt',
            prompt: 'Rank what agents asked for',
            title: 'MCP intent roundup',
            frequency: 'weekly',
            target_type: 'slack',
        })
    })

    it.each([
        ['an unsupported frequency', 'frequency=hourly', 'frequency', 'weekly'],
        ['a blank prompt', 'prompt=', 'prompt', undefined],
    ])('ignores %s in the prefill', async (_label, search, field, expected) => {
        const promptLogic = subscriptionLogic({ id: 'new' })
        promptLogic.mount()

        router.actions.push(`/subscriptions/new?${search}`)
        await expectLogic(promptLogic).toFinishListeners()

        expect(promptLogic.values.subscription[field as 'frequency' | 'prompt']).toBe(expected)
    })

    it('prefills an insight nudge with its own title and event', async () => {
        const insightLogic = subscriptionLogic({ insightShortId: '123' as InsightShortId, id: 'new' })
        insightLogic.mount()

        router.actions.push('/insights/123/subscriptions/new?prefill=nudge&via=export')
        await expectLogic(insightLogic).toFinishListeners()

        // An insight reaches this route without a name in hand, so its subscription is named for
        // the schedule rather than for the insight.
        expect(insightLogic.values.subscription).toMatchObject({
            title: 'Weekly digest',
            target_value: MOCK_DEFAULT_USER.email,
        })
        expect((posthog.capture as jest.Mock).mock.calls.filter(([name]) => name.endsWith('nudge clicked'))).toEqual([
            [
                'insight export nudge clicked',
                { kind: 'insight', insight_short_id: '123', prefilled: true, via: 'export' },
            ],
        ])

        insightLogic.unmount()
    })

    it('leaves a nudge for another subject to the form that owns it', async () => {
        // The route pattern matches any subject's page, so every mounted form sees this navigation.
        // One prefilling for someone else's nudge would discard what its own user had typed.
        const dashboardForm = subscriptionLogic({ dashboardId: 9, dashboardName: 'Key metrics', id: 'new' })
        const insightForm = subscriptionLogic({ insightShortId: '123' as InsightShortId, id: 'new' })
        dashboardForm.mount()
        insightForm.mount()

        router.actions.push('/dashboard/9/subscriptions/new?prefill=nudge&via=export')
        await expectLogic(dashboardForm).toFinishListeners()
        await expectLogic(insightForm).toFinishListeners()

        expect(dashboardForm.values.subscription).toMatchObject({ title: 'Key metrics weekly digest' })
        expect(insightForm.values.subscription.title).toBeUndefined()
        expect(insightForm.values.subscriptionChanged).toBe(false)
        // One click, reported once, against the dashboard.
        expect((posthog.capture as jest.Mock).mock.calls.filter(([name]) => name.endsWith('nudge clicked'))).toEqual([
            ['dashboard export nudge clicked', { kind: 'dashboard', dashboard_id: 9, prefilled: true, via: 'export' }],
        ])

        dashboardForm.unmount()
        insightForm.unmount()
    })

    it.each<[string, string, string, string]>([
        // The notification's source_url carries via=notification; the transient toast via=toast.
        // Absent via defaults to notification for safety. The export nudge is its own experiment,
        // so it reports a separate event instead of another `via` value on this one.
        ['?prefill=nudge&via=notification', 'notification', 'dashboard subscribe nudge clicked', 'notification link'],
        ['?prefill=nudge&via=toast', 'toast', 'dashboard subscribe nudge clicked', 'toast button'],
        ['?prefill=nudge&via=export', 'export', 'dashboard export nudge clicked', 'export toast button'],
        ['?prefill=nudge', 'notification', 'dashboard subscribe nudge clicked', 'legacy link without via'],
    ])(
        'prefills the form from %s and reports the click (via=%s, %s, %s)',
        async (search, expectedVia, expectedEvent) => {
            // The nudge notification can be clicked days later in a fresh session, so the prefill is
            // built from the URL param + logic context, not from any preexisting kea state.
            const prefilledLogic = subscriptionLogic({
                dashboardId: 9,
                dashboardName: 'Key metrics',
                id: 'new',
            })
            prefilledLogic.mount()

            router.actions.push(`/dashboard/9/subscriptions/new${search}`)
            await expectLogic(prefilledLogic).toFinishListeners()

            expect(prefilledLogic.values.subscription).toMatchObject({
                title: 'Key metrics weekly digest',
                target_value: MOCK_DEFAULT_USER.email,
                frequency: 'weekly',
                target_type: 'email',
            })
            expect(prefilledLogic.values.subscriptionChanged).toBe(true)
            // Matches on both nudge events, so a `via` routed to the wrong one fails here rather
            // than silently moving a conversion between the two experiments.
            const clickedCaptures = (): any[][] =>
                (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name.endsWith('nudge clicked'))
            expect(clickedCaptures()).toEqual([
                [expectedEvent, { kind: 'dashboard', dashboard_id: 9, prefilled: true, via: expectedVia }],
            ])

            // The params are consumed on apply, so refreshing the resulting URL neither re-captures
            // the click nor re-applies a stale prefill.
            expect(prefilledLogic.values.subscription.title).toBe('Key metrics weekly digest')
            expect(router.values.searchParams.prefill).toBeUndefined()
            expect(router.values.searchParams.via).toBeUndefined()
            router.actions.push(router.values.location.pathname)
            await expectLogic(prefilledLogic).toFinishListeners()
            expect(clickedCaptures()).toHaveLength(1)

            prefilledLogic.unmount()
        }
    )

    it.each<[string, boolean, boolean]>([
        // The prefill marks the form "changed" so Create is enabled, but the user never touched it —
        // navigating away must not pop the discard-changes prompt.
        ['an untouched prefilled form', false, false],
        // Any real edit on top of the prefill re-arms the prompt.
        ['a prefilled form the user then edited', true, true],
    ])('navigating away from %s prompts=%s', async (_label, editAfterPrefill, expectPrompt) => {
        const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
        const prefilledLogic = subscriptionLogic({
            dashboardId: 9,
            dashboardName: 'Key metrics',
            id: 'new',
        })
        prefilledLogic.mount()

        router.actions.push('/dashboard/9/subscriptions/new?prefill=nudge')
        await expectLogic(prefilledLogic).toFinishListeners()
        if (editAfterPrefill) {
            prefilledLogic.actions.setSubscriptionValue('title', 'My own title')
        }

        router.actions.push('/insights/123')

        expect(confirmSpy).toHaveBeenCalledTimes(expectPrompt ? 1 : 0)
        expect(router.values.location.pathname).toMatch(/\/insights\/123$/)

        prefilledLogic.unmount()
        confirmSpy.mockRestore()
    })

    it.each<[string, string, boolean]>([
        // The dashboard-with-tiles nudge flow: InsightSelector auto-selects right after the prefill.
        // A reset here would wipe the prefill's "changed" flag and disable Create.
        ['a prefilled form', '?prefill=nudge', true],
        // Plain new subscription keeps existing behavior: auto-select resets to a clean form.
        ['a plain new form', '', false],
    ])('insight auto-select on %s leaves the form changed=%s', async (_label, search, expectChanged) => {
        const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
        const testLogic = subscriptionLogic({
            dashboardId: 9,
            dashboardName: 'Key metrics',
            id: 'new',
        })
        testLogic.mount()

        router.actions.push(`/dashboard/9/subscriptions/new${search}`)
        await expectLogic(testLogic).toFinishListeners()

        testLogic.actions.applyDefaultSelectedInsights([101, 102])
        await expectLogic(testLogic).toFinishListeners()

        expect(testLogic.values.subscription.dashboard_export_insights).toEqual([101, 102])
        expect(testLogic.values.subscriptionChanged).toBe(expectChanged)

        // Either way the user never touched the form — navigating away must not prompt to discard.
        router.actions.push('/dashboard/9')
        expect(confirmSpy).not.toHaveBeenCalled()

        testLogic.unmount()
        confirmSpy.mockRestore()
    })

    it.each<[string, boolean, boolean, boolean]>([
        // The upsell mirrors the server-side create validation: consent + quota headroom required.
        ['consent accepted and quota ok', true, false, true],
        ['org AI consent missing', false, false, false],
        ['summary quota at limit', true, true, false],
    ])(
        'nudge prefill with %s defaults summary_enabled=%s without arming the discard prompt',
        async (_label, consentAccepted, atLimit, expectEnabled) => {
            const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
            // Settle the initial org load first, so the case's consent value can't be overwritten.
            await expectLogic(organizationLogic).toFinishAllListeners()
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: consentAccepted,
            })
            useMocks({
                get: {
                    '/api/environments/:team/subscriptions/summary_quota': {
                        active_count: 0,
                        limit: 5,
                        at_limit: atLimit,
                    },
                },
            })
            const prefilledLogic = subscriptionLogic({
                dashboardId: 9,
                dashboardName: 'Key metrics',
                id: 'new',
            })
            prefilledLogic.mount()

            router.actions.push('/dashboard/9/subscriptions/new?prefill=nudge')
            // The quota answer arrives after the prefill applied — the default is deferred to it.
            await expectLogic(prefilledLogic).toFinishAllListeners()

            expect(!!prefilledLogic.values.subscription.summary_enabled).toBe(expectEnabled)

            // Untouched form: the deferred default is folded into the prefill baseline, so
            // navigating away never prompts to discard.
            router.actions.push('/insights/123')
            expect(confirmSpy).not.toHaveBeenCalled()

            prefilledLogic.unmount()
            confirmSpy.mockRestore()
        }
    )

    it('respects a manual summary toggle-off after the default applied, and the edited form prompts on leave', async () => {
        const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
        await expectLogic(organizationLogic).toFinishAllListeners()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: true,
        })
        const prefilledLogic = subscriptionLogic({
            dashboardId: 9,
            dashboardName: 'Key metrics',
            id: 'new',
        })
        prefilledLogic.mount()

        router.actions.push('/dashboard/9/subscriptions/new?prefill=nudge')
        await expectLogic(prefilledLogic).toFinishAllListeners()
        expect(prefilledLogic.values.subscription.summary_enabled).toBe(true)

        // The user turns it back off; a later quota reload must not re-apply the default.
        prefilledLogic.actions.setSubscriptionValue('summary_enabled', false)
        await expectLogic(prefilledLogic, () => {
            prefilledLogic.actions.loadSummaryQuotaSuccess({ active_count: 0, limit: 5, at_limit: false })
        }).toFinishListeners()
        expect(prefilledLogic.values.subscription.summary_enabled).toBe(false)

        // The form now genuinely differs from the prefill baseline — leaving prompts.
        router.actions.push('/insights/123')
        expect(confirmSpy).toHaveBeenCalledTimes(1)

        prefilledLogic.unmount()
        confirmSpy.mockRestore()
    })

    it('leaves summary_enabled off for a plain non-nudge new subscription', async () => {
        router.actions.push('/insights/123/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()

        await expectLogic(newLogic, () => {
            newLogic.actions.loadSummaryQuotaSuccess({ active_count: 0, limit: 5, at_limit: false })
        }).toFinishListeners()

        expect(newLogic.values.subscription.summary_enabled).toBe(false)
    })

    it('still prompts when leaving a genuinely edited non-prefilled form', async () => {
        const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)

        router.actions.push('/insights/123/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValue('title', 'My own title')

        router.actions.push('/insights/123')

        expect(confirmSpy).toHaveBeenCalledWith('Changes you made will be discarded.')
        confirmSpy.mockRestore()
    })

    it('does not toast when kea-forms reports client validation failure', async () => {
        await expectLogic(newLogic, () => {
            newLogic.actions.submitSubscriptionFailure(new Error('Validation Failed'), {})
        }).toFinishListeners()
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('toasts and maps ApiError attr to manual errors on save failure', async () => {
        const err = new ApiError('Select at least one insight', 400, undefined, {
            type: 'validation_error',
            attr: 'dashboard_export_insights',
            detail: 'Select at least one insight',
        })
        await expectLogic(newLogic, () => {
            newLogic.actions.submitSubscriptionFailure(err, {})
        }).toFinishListeners()
        expect(lemonToast.error).toHaveBeenCalledWith('Select at least one insight')
        expect(newLogic.values.subscriptionManualErrors).toEqual({
            dashboard_export_insights: 'Select at least one insight',
        })
    })

    it.each<[string, Partial<SubscriptionType>, string[]]>([
        ['a slack subscription', { target_type: 'slack', target_value: 'C123|#general', integration_id: 7 }, ['C123']],
        [
            'a non-slack target type',
            { target_type: 'email', target_value: 'ben@posthog.com', integration_id: null },
            [],
        ],
    ])('records the channel recency for %s', async (_label, subscription, expectedIds) => {
        await expectLogic(newLogic, () => {
            newLogic.actions.submitSubscriptionSuccess(subscription as SubscriptionType)
        }).toFinishListeners()

        expect(getRecentSlackChannelIds(7)).toEqual(expectedIds)
    })

    it('rejects empty prompt when resource_type is ai_prompt', async () => {
        // The parent-less /subscriptions/new route is the AI flow; its urlToAction sets
        // resource_type='ai_prompt' (the /insights/... route forces 'insight').
        router.actions.push('/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({ resource_type: 'ai_prompt', prompt: '   ', title: 'AI test' })
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscriptionErrors.prompt).toBeTruthy()
    })

    it('rejects prompts exceeding 4000 characters when resource_type is ai_prompt', async () => {
        router.actions.push('/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({
            resource_type: 'ai_prompt',
            prompt: 'x'.repeat(4001),
            title: 'AI test',
        })
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscriptionErrors.prompt).toContain('4000')
    })

    it('accepts a valid AI prompt', async () => {
        router.actions.push('/insights/123/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({
            resource_type: 'ai_prompt',
            prompt: 'Show me the biggest event gains last week',
            title: 'AI test',
        })
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscriptionErrors.prompt).toBeUndefined()
    })

    it('clears a carried-over insight selection when saving an AI subscription', async () => {
        // Opening the AI flow from a dashboard pre-populates dashboard_export_insights;
        // those must not be sent, else the backend rejects insights without a dashboard.
        let capturedBody: Partial<SubscriptionType> | undefined
        useMocks({
            post: {
                '/api/environments/:team/subscriptions': async ({ request }) => {
                    capturedBody = (await request.json()) as Partial<SubscriptionType>
                    return [200, { id: 42, ...capturedBody } as SubscriptionType]
                },
            },
        })
        router.actions.push('/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({
            resource_type: 'ai_prompt',
            prompt: 'Show me the biggest event gains last week',
            title: 'AI test',
            target_type: 'email',
            target_value: 'ben@posthog.com',
            dashboard_export_insights: [1, 2, 3],
        })
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners().toDispatchActions(['submitSubscriptionSuccess'])
        expect(capturedBody?.dashboard_export_insights).toEqual([])
        expect(capturedBody?.dashboard).toBeUndefined()
        expect(capturedBody?.insight).toBeUndefined()
    })

    it('drops a stale prompt when saving a non-AI subscription', async () => {
        // Toggling resource_type back to insight after typing a prompt leaves it in form state;
        // it must not be sent, else the backend rejects a non-AI sub that carries a prompt.
        let capturedBody: Partial<SubscriptionType> | undefined
        useMocks({
            post: {
                '/api/environments/:team/subscriptions': async ({ request }) => {
                    capturedBody = (await request.json()) as Partial<SubscriptionType>
                    return [200, { id: 43, ...capturedBody } as SubscriptionType]
                },
            },
        })
        router.actions.push('/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({
            resource_type: 'insight',
            prompt: 'stale prompt left over from the AI toggle',
            title: 'Insight test',
            target_type: 'email',
            target_value: 'ben@posthog.com',
        })
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners().toDispatchActions(['submitSubscriptionSuccess'])
        expect(capturedBody?.prompt).toBeUndefined()
    })
})
