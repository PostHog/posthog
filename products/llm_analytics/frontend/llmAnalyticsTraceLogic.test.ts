import { MOCK_TEAM_ID } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DisplayOption, llmAnalyticsTraceLogic } from './llmAnalyticsTraceLogic'

describe('llmAnalyticsTraceLogic', () => {
    let logic: ReturnType<typeof llmAnalyticsTraceLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/query/': { results: [] },
            },
        })
        initKeaTests()
        logic = llmAnalyticsTraceLogic()
        logic.mount()
    })

    it('properly loads trace scene when trace ID contains a colon', async () => {
        const traceIdWithColon = 'session-summary:group:16-16:81008d53ff0a708b:da6c0390-409f-485c-aab3-5e910bcf8b33'
        const traceUrl = combineUrl(urls.llmAnalyticsTrace(traceIdWithColon))
        const finalUrl = addProjectIdIfMissing(traceUrl.url, MOCK_TEAM_ID)

        router.actions.push(finalUrl)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.traceId).toBe(traceIdWithColon)
    })

    it('properly loads trace scene when trace ID contains multiple colons', async () => {
        const traceIdWithMultipleColons = 'namespace:trace:12345:abcdef:xyz'
        const traceUrl = combineUrl(urls.llmAnalyticsTrace(traceIdWithMultipleColons))

        router.actions.push(addProjectIdIfMissing(traceUrl.url, MOCK_TEAM_ID))
        await expectLogic(logic).toMatchValues({
            traceId: traceIdWithMultipleColons,
        })
    })

    it('handles trace ID with event and timestamp parameters', async () => {
        const traceIdWithColon = 'session-summary:group:16-16:81008d53ff0a708b:da6c0390-409f-485c-aab3-5e910bcf8b33'
        const eventId = 'event123'
        const timestamp = '2024-01-01T00:00:00Z'
        const traceUrl = combineUrl(urls.llmAnalyticsTrace(traceIdWithColon, { event: eventId, timestamp }))

        router.actions.push(addProjectIdIfMissing(traceUrl.url, MOCK_TEAM_ID))
        await expectLogic(logic).toMatchValues({
            traceId: traceIdWithColon,
            eventId: eventId,
            dateRange: { dateFrom: timestamp, dateTo: null },
        })
    })

    it('handles trace ID with event and exception_ts parameters', async () => {
        const traceIdWithColon = 'session-summary:group:16-16:81008d53ff0a708b:da6c0390-409f-485c-aab3-5e910bcf8b33'
        const eventId = 'event123'
        const exception_ts = '2024-01-02T00:00:00Z'
        const traceUrl = combineUrl(urls.llmAnalyticsTrace(traceIdWithColon, { event: eventId, exception_ts }))

        router.actions.push(addProjectIdIfMissing(traceUrl.url, MOCK_TEAM_ID))
        await expectLogic(logic).toMatchValues({
            traceId: traceIdWithColon,
            eventId: eventId,
            dateRange: { dateFrom: '2024-01-01T23:40:00.000Z', dateTo: '2024-01-02T00:20:00.000Z' },
        })
    })

    describe('messageShowStates reducer', () => {
        it('has correct initial state', () => {
            expect(logic.values.messageShowStates).toEqual({
                input: [],
                output: [],
            })
        })

        it('initializes message states with specified counts', async () => {
            await expectLogic(logic, () => {
                logic.actions.initializeMessageStates(3, 2)
            })
                .toDispatchActions(['initializeMessageStates', 'applySearchResults'])
                .toMatchValues({
                    messageShowStates: {
                        input: [false, false, true],
                        output: [true, true],
                    },
                })
        })

        it('toggles individual message visibility', async () => {
            logic.actions.initializeMessageStates(2, 2)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.toggleMessage('input', 0)
            }).toMatchValues({
                messageShowStates: {
                    input: [true, true],
                    output: [true, true],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.toggleMessage('output', 1)
            }).toMatchValues({
                messageShowStates: {
                    input: [true, true],
                    output: [true, false],
                },
            })
        })

        it('shows all messages of a specific type', async () => {
            logic.actions.initializeMessageStates(3, 2)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.showAllMessages('input')
            }).toMatchValues({
                messageShowStates: {
                    input: [true, true, true],
                    output: [true, true],
                },
            })
        })

        it('hides all messages of a specific type', async () => {
            logic.actions.initializeMessageStates(2, 3)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.hideAllMessages('output')
            }).toMatchValues({
                messageShowStates: {
                    input: [false, true],
                    output: [false, false, false],
                },
            })
        })

        it('applies search results to message states', async () => {
            const inputMatches = [true, false, true]
            const outputMatches = [false, true]

            await expectLogic(logic, () => {
                logic.actions.applySearchResults(inputMatches, outputMatches)
            }).toMatchValues({
                messageShowStates: {
                    input: inputMatches,
                    output: outputMatches,
                },
            })
        })

        it('preserves state when search query changes', async () => {
            logic.actions.initializeMessageStates(2, 2)
            await expectLogic(logic).toFinishAllListeners()

            const currentState = logic.values.messageShowStates

            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('test query')
            })
                .toDispatchActions(['setSearchQuery'])
                .toMatchValues({
                    messageShowStates: currentState,
                })
        })
    })

    describe('searchQuery reducer', () => {
        it('has empty initial state', () => {
            expect(logic.values.searchQuery).toBe('')
        })

        it('sets search query to provided string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('test search')
            }).toMatchValues({
                searchQuery: 'test search',
            })
        })

        it('converts non-string values to string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery(123 as any)
            }).toMatchValues({
                searchQuery: '123',
            })
        })

        it('handles null and undefined by converting to empty string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery(null as any)
            }).toMatchValues({
                searchQuery: '',
            })

            await expectLogic(logic, () => {
                logic.actions.setSearchQuery(undefined as any)
            }).toMatchValues({
                searchQuery: '',
            })
        })

        it('clears search query when empty string is provided', async () => {
            logic.actions.setSearchQuery('initial search')
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('')
            }).toMatchValues({
                searchQuery: '',
            })
        })
    })

    describe('selectors', () => {
        describe('inputMessageShowStates', () => {
            it('returns input states from messageShowStates', async () => {
                const inputStates = [true, false, true]
                const outputStates = [false, false]

                logic.actions.applySearchResults(inputStates, outputStates)
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.inputMessageShowStates).toEqual(inputStates)
            })

            it('returns empty array when no states initialized', () => {
                expect(logic.values.inputMessageShowStates).toEqual([])
            })
        })

        describe('outputMessageShowStates', () => {
            it('returns output states from messageShowStates', async () => {
                const inputStates = [true, false]
                const outputStates = [true, true, false]

                logic.actions.applySearchResults(inputStates, outputStates)
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.outputMessageShowStates).toEqual(outputStates)
            })

            it('returns empty array when no states initialized', () => {
                expect(logic.values.outputMessageShowStates).toEqual([])
            })
        })
    })

    describe('initializeMessageStates listener', () => {
        it('applies ExpandAll display option', async () => {
            logic.actions.setDisplayOption(DisplayOption.ExpandAll)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.initializeMessageStates(3, 2)
            })
                .toDispatchActions(['initializeMessageStates', 'applySearchResults'])
                .toMatchValues({
                    messageShowStates: {
                        input: [true, true, true],
                        output: [true, true],
                    },
                })
        })

        it('applies CollapseExceptOutputAndLastInput display option', async () => {
            logic.actions.setDisplayOption(DisplayOption.CollapseExceptOutputAndLastInput)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.initializeMessageStates(4, 3)
            })
                .toDispatchActions(['initializeMessageStates', 'applySearchResults'])
                .toMatchValues({
                    messageShowStates: {
                        input: [false, false, false, true],
                        output: [true, true, true],
                    },
                })
        })

        it('handles single input message correctly', async () => {
            logic.actions.setDisplayOption(DisplayOption.CollapseExceptOutputAndLastInput)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.initializeMessageStates(1, 2)
            })
                .toDispatchActions(['initializeMessageStates', 'applySearchResults'])
                .toMatchValues({
                    messageShowStates: {
                        input: [true],
                        output: [true, true],
                    },
                })
        })

        it('handles zero messages correctly', async () => {
            await expectLogic(logic, () => {
                logic.actions.initializeMessageStates(0, 0)
            })
                .toDispatchActions(['initializeMessageStates', 'applySearchResults'])
                .toMatchValues({
                    messageShowStates: {
                        input: [],
                        output: [],
                    },
                })
        })
    })

    describe('setSearchQuery URL updates', () => {
        let routerSpy: jest.SpyInstance

        beforeEach(() => {
            const mockLocation = {
                search: '',
            }
            Object.defineProperty(window, 'location', {
                value: mockLocation,
                writable: true,
                configurable: true,
            })
            routerSpy = jest.spyOn(router.actions, 'replace').mockImplementation(() => {})
        })

        afterEach(() => {
            routerSpy.mockRestore()
        })

        it('updates URL when search query changes and includes event and timestamp in URL update', async () => {
            logic.actions.setTraceId('test-trace-123')
            logic.actions.setEventId('event-456')
            logic.actions.setDateRange('2024-01-01T00:00:00Z')
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSearchQuery('search with params')
            await expectLogic(logic).toFinishAllListeners()

            expect(routerSpy).toHaveBeenCalledWith(
                urls.llmAnalyticsTrace('test-trace-123', {
                    event: 'event-456',
                    timestamp: '2024-01-01T00:00:00Z',
                    search: 'search with params',
                })
            )
        })

        it('removes search param from URL when query is cleared', async () => {
            window.location.search = '?search=existing'
            logic.actions.setTraceId('test-trace-123')
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSearchQuery('')
            await expectLogic(logic).toFinishAllListeners()

            expect(routerSpy).toHaveBeenCalledWith(urls.llmAnalyticsTrace('test-trace-123', {}))
        })

        it('does not update URL when search query matches URL param', async () => {
            window.location.search = '?search=existing'
            logic.actions.setTraceId('test-trace-123')
            await expectLogic(logic).toFinishAllListeners()

            routerSpy.mockClear()

            logic.actions.setSearchQuery('existing')
            await expectLogic(logic).toFinishAllListeners()

            expect(routerSpy).not.toHaveBeenCalled()
        })
    })
})
