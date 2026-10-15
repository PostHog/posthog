import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import posthog from 'lib/posthog-typed'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { subscriptionsCreate, subscriptionsList } from 'products/subscriptions/frontend/generated/api'
import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { mcpAnalyticsSessionsActivityOverview } from '../generated/api'
import type { MCPActivityOverviewApi } from '../generated/api.schemas'
import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { mcpRecurringReportsLogic } from '../notifications/mcpRecurringReportsLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

jest.mock('lib/api')
jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn(), captureRaw: jest.fn() } }))
jest.mock('../generated/api', () => ({ mcpAnalyticsSessionsActivityOverview: jest.fn() }))
jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsList: jest.fn(),
    subscriptionsCreate: jest.fn(),
}))

const overviewMock = mcpAnalyticsSessionsActivityOverview as jest.Mock
const captureRawMock = posthog.captureRaw as jest.Mock
const createReportMock = subscriptionsCreate as jest.Mock

function overviewWith(stats: Partial<MCPActivityOverviewApi['stats']>): MCPActivityOverviewApi {
    return {
        stats: {
            total_calls: 40,
            distinct_tools: 5,
            distinct_sessions: 8,
            distinct_clients: 2,
            calls_with_intent: 35,
            error_calls: 0,
            missing_capability_reports: 0,
            ...stats,
        },
        top_tools: [],
        clients: [],
        recent_calls: [],
    }
}

const LANDED_REPORT = {
    id: 5,
    enabled: true,
    prompt: 'Report on $mcp_tool_name',
    target_type: 'email',
} as SubscriptionApi

const INTENT_AND_ALERT_STEPS = overviewWith({ calls_with_intent: 2, error_calls: 3 })
const ALERT_STEP_ONLY = overviewWith({ error_calls: 3 })
const NO_STEPS = overviewWith({})

function eventsNamed(name: string): unknown[][] {
    return captureRawMock.mock.calls.filter(([event]) => event === name).map(([, properties]) => properties)
}

const TOOL_FILTER: AnyPropertyFilter = {
    key: '$mcp_tool_name',
    value: ['create_insight'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

describe('mcpEarlyDataLogic', () => {
    let logic: ReturnType<typeof mcpEarlyDataLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api as jest.Mocked<typeof api>, 'query').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        overviewMock.mockResolvedValue(null)
        ;(subscriptionsList as jest.Mock).mockResolvedValue({ next: null, previous: null, results: [] })
        logic = mcpEarlyDataLogic()
        logic.mount()
    })

    // Self-hosted instances never see the weekly report, so the other steps show alone.
    async function resolveOffer(cloud: boolean): Promise<void> {
        // Let the mounted preflight request land first, so it cannot overwrite the answer set here.
        await expectLogic(preflightLogic).toFinishAllListeners()
        preflightLogic.actions.loadPreflightSuccess({ cloud, is_debug: false } as any)
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT], {
            [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true,
        })
    }

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it.each([
        [
            'restored URL filters',
            () => mcpAnalyticsFiltersLogic.actions.hydrateFilters(true, [TOOL_FILTER]),
            { filter_test_accounts: true, properties: expect.stringContaining('$mcp_tool_name') },
            { filterTestAccounts: true, properties: [TOOL_FILTER] },
        ],
        [
            'property filters',
            () => mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER]),
            { properties: expect.stringContaining('$mcp_tool_name') },
            { filterTestAccounts: false, properties: [TOOL_FILTER] },
        ],
        [
            'the test-account switch',
            () => mcpAnalyticsFiltersLogic.actions.setFilterTestAccounts(true),
            { filter_test_accounts: true },
            { filterTestAccounts: true, properties: [] },
        ],
    ])('refetches activity with %s', async (_label, change, expectedParams, expectedQuery) => {
        await expectLogic(logic).toFinishAllListeners()
        overviewMock.mockClear()

        await expectLogic(logic, change).toDispatchActions(['loadOverviewSuccess'])

        expect(overviewMock).toHaveBeenCalledTimes(1)
        expect(overviewMock.mock.calls[0][1]).toMatchObject(expectedParams)
        expect(logic.values.activityQuery.source).toMatchObject(expectedQuery)
    })

    it.each([
        ['one refresh with steps', [INTENT_AND_ALERT_STEPS], [['intent', 'notification']]],
        [
            'the same steps after the 60s refresh',
            [INTENT_AND_ALERT_STEPS, overviewWith({ calls_with_intent: 2, error_calls: 3 })],
            [['intent', 'notification']],
        ],
        [
            'a step done in between',
            [INTENT_AND_ALERT_STEPS, ALERT_STEP_ONLY],
            [['intent', 'notification'], ['notification']],
        ],
        ['no steps to show', [NO_STEPS], []],
        [
            'the steps coming back after none',
            [INTENT_AND_ALERT_STEPS, NO_STEPS, INTENT_AND_ALERT_STEPS],
            [
                ['intent', 'notification'],
                ['intent', 'notification'],
            ],
        ],
    ])('reports the steps shown for %s', async (_label, overviews, expectedShown) => {
        await resolveOffer(false)
        await expectLogic(logic).toFinishAllListeners()
        captureRawMock.mockClear()

        for (const overview of overviews) {
            overviewMock.mockResolvedValue(overview)
            await expectLogic(logic, () => logic.actions.loadOverview()).toFinishAllListeners()
        }

        expect(eventsNamed('mcp analytics next steps shown').map((properties: any) => properties.step_keys)).toEqual(
            expectedShown
        )
    })

    it.each([
        ['loads', false],
        ['fails to load', true],
    ])('holds the card until the alert list %s, then reports it once', async (_label, listFails) => {
        await resolveOffer(false)
        logic.unmount()
        let settleList!: () => void
        const list = new Promise<Awaited<ReturnType<typeof api.hogFunctions.list>>>((resolve, reject) => {
            settleList = () =>
                listFails ? reject(new Error('down')) : resolve({ count: 0, next: null, previous: null, results: [] })
        })
        jest.spyOn(api.hogFunctions, 'list').mockReturnValue(list)
        overviewMock.mockResolvedValue(INTENT_AND_ALERT_STEPS)
        captureRawMock.mockClear()
        logic = mcpEarlyDataLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadOverviewSuccess'])

        expect(logic.values.nextSteps).toBeNull()
        expect(eventsNamed('mcp analytics next steps shown')).toEqual([])

        settleList()
        await expectLogic(logic).toFinishAllListeners()

        expect(eventsNamed('mcp analytics next steps shown').map((properties: any) => properties.step_keys)).toEqual([
            ['intent', 'notification'],
        ])
    })

    it('reports how much data stood behind the steps shown and why the report is missing', async () => {
        await resolveOffer(false)
        await expectLogic(logic).toFinishAllListeners()
        captureRawMock.mockClear()
        overviewMock.mockResolvedValue(INTENT_AND_ALERT_STEPS)

        await expectLogic(logic, () => logic.actions.loadOverview()).toFinishAllListeners()

        expect(eventsNamed('mcp analytics next steps shown')).toEqual([
            {
                step_keys: ['intent', 'notification'],
                weekly_report: 'hidden:self-hosted',
                total_calls: 40,
                error_calls: 3,
            },
        ])
    })

    it.each([
        ['loads', false, ['weekly-report', 'intent', 'notification']],
        ['fails to load', true, ['intent', 'notification']],
    ])('holds the card until the report list %s, then reports it once', async (_label, listFails, expectedKeys) => {
        await resolveOffer(true)
        logic.unmount()
        let settleList!: () => void
        const list = new Promise<{ next: null; previous: null; results: [] }>((resolve, reject) => {
            settleList = () =>
                listFails ? reject(new Error('down')) : resolve({ next: null, previous: null, results: [] })
        })
        ;(subscriptionsList as jest.Mock).mockReturnValue(list)
        overviewMock.mockResolvedValue(INTENT_AND_ALERT_STEPS)
        captureRawMock.mockClear()
        logic = mcpEarlyDataLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadOverviewSuccess', 'loadNotificationsSuccess'])

        expect(logic.values.nextSteps).toBeNull()
        expect(eventsNamed('mcp analytics next steps shown')).toEqual([])

        settleList()
        await expectLogic(logic).toFinishAllListeners()

        expect(eventsNamed('mcp analytics next steps shown').map((properties: any) => properties.step_keys)).toEqual([
            expectedKeys,
        ])
    })

    it('holds the card back until the weekly report offer is known', async () => {
        overviewMock.mockResolvedValue(INTENT_AND_ALERT_STEPS)
        await expectLogic(logic, () => logic.actions.loadOverview()).toFinishAllListeners()
        expect(logic.values.nextSteps).toBeNull()

        await resolveOffer(true)

        expect(logic.values.nextSteps?.map((step) => step.key)).toEqual(['weekly-report', 'intent', 'notification'])
    })

    it.each([
        ['intent', 'open', 0],
        ['intent', 'docs', 0],
        ['notification', 'open', 1],
    ] as const)('reports a %s click with interaction %s at position %s', async (stepKey, interaction, position) => {
        await resolveOffer(false)
        overviewMock.mockResolvedValue(INTENT_AND_ALERT_STEPS)
        await expectLogic(logic, () => logic.actions.loadOverview()).toFinishAllListeners()
        captureRawMock.mockClear()

        logic.actions.nextStepClicked(stepKey, interaction)

        expect(eventsNamed('mcp analytics next step clicked')).toEqual([
            { step_key: stepKey, interaction, position, weekly_report: 'hidden:self-hosted' },
        ])
    })

    describe('with the weekly report on offer', () => {
        beforeEach(async () => {
            await resolveOffer(true)
            overviewMock.mockResolvedValue(INTENT_AND_ALERT_STEPS)
            createReportMock.mockResolvedValue({ id: 5, target_type: 'email' } as SubscriptionApi)
            await expectLogic(logic, () => logic.actions.loadOverview()).toFinishAllListeners()
        })

        it('reports the steps shown with the report leading and its state', () => {
            expect(eventsNamed('mcp analytics next steps shown')).toEqual([
                {
                    step_keys: ['weekly-report', 'intent', 'notification'],
                    weekly_report: 'ready',
                    total_calls: 40,
                    error_calls: 3,
                },
            ])
        })

        it.each([
            ['succeeds', () => Promise.resolve(LANDED_REPORT), []],
            ['is refused', () => Promise.reject(new ApiError('Bad Request', 400)), []],
            [
                'fails in transit after the report landed',
                () => {
                    ;(subscriptionsList as jest.Mock).mockResolvedValue({
                        next: null,
                        previous: null,
                        results: [LANDED_REPORT],
                    })
                    return Promise.reject(new Error('network'))
                },
                [['intent', 'notification']],
            ],
        ])(
            'reports the steps again only if creating the report %s changes them',
            async (_label, create, expectedShown) => {
                createReportMock.mockImplementation(create)
                captureRawMock.mockClear()

                mcpRecurringReportsLogic.actions.createWeeklyReport()
                await expectLogic(logic).toFinishAllListeners()

                expect(
                    eventsNamed('mcp analytics next steps shown').map((properties: any) => properties.step_keys)
                ).toEqual(expectedShown)
            }
        )

        it.each(['create-report', 'open-consent', 'manage-report', 'more-options'] as const)(
            'a %s click only reports the click, with the offer state',
            async (interaction) => {
                captureRawMock.mockClear()

                logic.actions.nextStepClicked('weekly-report', interaction)
                await expectLogic(logic).toFinishAllListeners()

                expect(createReportMock).not.toHaveBeenCalled()
                expect(eventsNamed('mcp analytics next step clicked')).toEqual([
                    { step_key: 'weekly-report', interaction, position: 0, weekly_report: 'ready' },
                ])
            }
        )
    })
})
