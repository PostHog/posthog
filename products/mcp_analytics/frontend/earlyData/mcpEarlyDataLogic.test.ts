import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import posthog from 'lib/posthog-typed'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { mcpAnalyticsSessionsActivityOverview } from '../generated/api'
import type { MCPActivityOverviewApi } from '../generated/api.schemas'
import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

jest.mock('lib/api')
jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn(), captureRaw: jest.fn() } }))
jest.mock('../generated/api', () => ({ mcpAnalyticsSessionsActivityOverview: jest.fn() }))

const overviewMock = mcpAnalyticsSessionsActivityOverview as jest.Mock
const captureRawMock = posthog.captureRaw as jest.Mock

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
        logic = mcpEarlyDataLogic()
        logic.mount()
    })

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

    it('reports how much data stood behind the steps shown', async () => {
        await expectLogic(logic).toFinishAllListeners()
        captureRawMock.mockClear()
        overviewMock.mockResolvedValue(INTENT_AND_ALERT_STEPS)

        await expectLogic(logic, () => logic.actions.loadOverview()).toFinishAllListeners()

        expect(eventsNamed('mcp analytics next steps shown')).toEqual([
            { step_keys: ['intent', 'notification'], total_calls: 40, error_calls: 3 },
        ])
    })

    it.each([
        ['intent', 'open', 0],
        ['intent', 'docs', 0],
        ['notification', 'open', 1],
    ] as const)('reports a %s click with interaction %s at position %s', async (stepKey, interaction, position) => {
        overviewMock.mockResolvedValue(INTENT_AND_ALERT_STEPS)
        await expectLogic(logic, () => logic.actions.loadOverview()).toFinishAllListeners()
        captureRawMock.mockClear()

        logic.actions.nextStepClicked(stepKey, interaction)

        expect(eventsNamed('mcp analytics next step clicked')).toEqual([{ step_key: stepKey, interaction, position }])
    })
})
