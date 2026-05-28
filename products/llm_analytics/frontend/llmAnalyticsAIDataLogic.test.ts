import { expectLogic } from 'kea-test-utils'

import api from '~/lib/api'
import { initKeaTests } from '~/test/init'

import { llmAnalyticsAIDataLogic } from './llmAnalyticsAIDataLogic'

jest.mock('~/lib/api')

const mockApi = api as jest.Mocked<typeof api>

describe('llmAnalyticsAIDataLogic', () => {
    beforeEach(() => {
        jest.resetAllMocks()
        initKeaTests()
    })

    it('passes through when both input and output are already present — no TraceQuery fetch', async () => {
        const logic = llmAnalyticsAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: [{ role: 'user', content: 'hi' }],
                output: [{ role: 'assistant', content: 'hello' }],
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
                aiEventsRolloutEnabled: true,
            })
        })
            .toFinishAllListeners()
            .toMatchValues({
                aiDataCache: {
                    'event-1': {
                        input: [{ role: 'user', content: 'hi' }],
                        output: [{ role: 'assistant', content: 'hello' }],
                        tools: undefined,
                    },
                },
            })

        expect(mockApi.query).not.toHaveBeenCalled()
    })

    it('fetches via TraceQuery and populates heavy props when input is missing', async () => {
        jest.spyOn(mockApi, 'query').mockResolvedValue({
            results: [
                {
                    id: 'trace-1',
                    events: [
                        {
                            id: 'event-1',
                            event: '$ai_generation',
                            createdAt: '2026-04-30T10:00:00Z',
                            properties: {
                                $ai_input: [{ role: 'user', content: 'post-strip hi' }],
                                $ai_output_choices: [{ role: 'assistant', content: 'post-strip hello' }],
                                $ai_tools: [{ function: { name: 'search' } }],
                            },
                        },
                        {
                            id: 'event-2',
                            event: '$ai_span',
                            createdAt: '2026-04-30T10:00:01Z',
                            properties: {},
                        },
                    ],
                },
            ],
        } as any)

        const logic = llmAnalyticsAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
                aiEventsRolloutEnabled: true,
            })
        })
            .toFinishAllListeners()
            .toMatchValues({
                aiDataCache: {
                    'event-1': {
                        input: [{ role: 'user', content: 'post-strip hi' }],
                        output: [{ role: 'assistant', content: 'post-strip hello' }],
                        tools: [{ function: { name: 'search' } }],
                    },
                },
            })

        expect(mockApi.query).toHaveBeenCalledTimes(1)
    })

    it('degrades gracefully to the passed-in values when TraceQuery throws', async () => {
        jest.spyOn(mockApi, 'query').mockRejectedValue(new Error('network down'))

        const logic = llmAnalyticsAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: 'fallback-input',
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
                aiEventsRolloutEnabled: true,
            })
        })
            .toFinishAllListeners()
            .toMatchValues({
                aiDataCache: {
                    'event-1': {
                        input: 'fallback-input',
                        output: undefined,
                        tools: undefined,
                    },
                },
            })
    })

    it.each([
        ['traceId missing', { traceId: undefined, timestamp: '2026-04-30T10:00:00Z' }],
        ['timestamp missing', { traceId: 'trace-1', timestamp: undefined }],
        ['both missing', { traceId: undefined, timestamp: undefined }],
    ])('skips the fetch when trace coordinates are incomplete (%s)', async (_label, coords) => {
        const querySpy = jest.spyOn(mockApi, 'query')

        const logic = llmAnalyticsAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                aiEventsRolloutEnabled: true,
                ...coords,
            })
        }).toFinishAllListeners()

        expect(querySpy).not.toHaveBeenCalled()
    })

    it('skips the fetch when the ai-events-table-rollout flag is off', async () => {
        const querySpy = jest.spyOn(mockApi, 'query')

        const logic = llmAnalyticsAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
                aiEventsRolloutEnabled: false,
            })
        }).toFinishAllListeners()

        expect(querySpy).not.toHaveBeenCalled()
    })
})
