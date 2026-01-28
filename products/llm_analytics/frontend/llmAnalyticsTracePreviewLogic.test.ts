import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { DisplayOption, TraceViewMode } from './llmAnalyticsTraceLogic'
import { llmAnalyticsTracePreviewLogic } from './llmAnalyticsTracePreviewLogic'

const createValidTraceJson = (overrides: Record<string, unknown> = {}): string =>
    JSON.stringify({
        trace_id: 'test-trace-123',
        timestamp: '2025-01-15T10:00:00Z',
        total_tokens: { input: 100, output: 50 },
        events: [
            {
                type: 'generation',
                name: 'Test Generation',
                model: 'gpt-4',
            },
        ],
        ...overrides,
    })

describe('llmAnalyticsTracePreviewLogic', () => {
    let logic: ReturnType<typeof llmAnalyticsTracePreviewLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = llmAnalyticsTracePreviewLogic()
        logic.mount()
    })

    describe('default state', () => {
        it('has correct default values', () => {
            expectLogic(logic).toMatchValues({
                rawJson: '',
                parsedTraceData: null,
                validationError: null,
                selectedEventId: null,
                viewMode: TraceViewMode.Conversation,
                searchQuery: '',
                displayOption: DisplayOption.CollapseExceptOutputAndLastInput,
                messageShowStates: { input: [], output: [] },
                isRenderingMarkdown: true,
                isRenderingXml: false,
                eventTypeExpandedMap: {},
                hasTrace: false,
            })
        })
    })

    describe('simple reducer actions', () => {
        it('setRawJson updates the raw JSON', () => {
            expectLogic(logic, () => {
                logic.actions.setRawJson('{"test": true}')
            }).toMatchValues({
                rawJson: '{"test": true}',
            })
        })

        it('setSelectedEventId updates selectedEventId', () => {
            expectLogic(logic, () => {
                logic.actions.setSelectedEventId('event-123')
            }).toMatchValues({
                selectedEventId: 'event-123',
            })
        })

        it('setViewMode updates viewMode', () => {
            expectLogic(logic, () => {
                logic.actions.setViewMode(TraceViewMode.Raw)
            }).toMatchValues({
                viewMode: TraceViewMode.Raw,
            })
        })

        it('setSearchQuery updates searchQuery', () => {
            expectLogic(logic, () => {
                logic.actions.setSearchQuery('test query')
            }).toMatchValues({
                searchQuery: 'test query',
            })
        })

        it('setDisplayOption updates displayOption', () => {
            expectLogic(logic, () => {
                logic.actions.setDisplayOption(DisplayOption.ExpandAll)
            }).toMatchValues({
                displayOption: DisplayOption.ExpandAll,
            })
        })

        it('setValidationError updates validationError', () => {
            expectLogic(logic, () => {
                logic.actions.setValidationError('Some error')
            }).toMatchValues({
                validationError: 'Some error',
            })
        })

        it('setRawJson clears validationError', () => {
            expectLogic(logic, () => {
                logic.actions.setValidationError('Some error')
                logic.actions.setRawJson('new json')
            }).toMatchValues({
                validationError: null,
                rawJson: 'new json',
            })
        })

        it('clearTrace resets all state to defaults', () => {
            expectLogic(logic, () => {
                logic.actions.setRawJson('{"test": true}')
                logic.actions.setSelectedEventId('event-123')
                logic.actions.setSearchQuery('query')
                logic.actions.setValidationError('error')
                logic.actions.initializeMessageStates(2, 3)
                logic.actions.toggleEventTypeExpanded('generation')
                logic.actions.clearTrace()
            }).toMatchValues({
                rawJson: '',
                parsedTraceData: null,
                validationError: null,
                selectedEventId: null,
                searchQuery: '',
                messageShowStates: { input: [], output: [] },
                eventTypeExpandedMap: {},
            })
        })
    })

    describe('message show states', () => {
        it('initializeMessageStates creates arrays with correct lengths and default values', () => {
            expectLogic(logic, () => {
                logic.actions.initializeMessageStates(3, 2)
            }).toMatchValues({
                messageShowStates: {
                    input: [false, false, false],
                    output: [true, true],
                },
            })
        })

        it('toggleMessage flips a single message state', () => {
            expectLogic(logic, () => {
                logic.actions.initializeMessageStates(3, 2)
                logic.actions.toggleMessage('input', 1)
            }).toMatchValues({
                messageShowStates: {
                    input: [false, true, false],
                    output: [true, true],
                },
            })

            expectLogic(logic, () => {
                logic.actions.toggleMessage('output', 0)
            }).toMatchValues({
                messageShowStates: {
                    input: [false, true, false],
                    output: [false, true],
                },
            })
        })

        it('showAllMessages sets all states for a type to true', () => {
            expectLogic(logic, () => {
                logic.actions.initializeMessageStates(3, 2)
                logic.actions.showAllMessages('input')
            }).toMatchValues({
                messageShowStates: {
                    input: [true, true, true],
                    output: [true, true],
                },
            })
        })

        it('hideAllMessages sets all states for a type to false', () => {
            expectLogic(logic, () => {
                logic.actions.initializeMessageStates(3, 2)
                logic.actions.hideAllMessages('output')
            }).toMatchValues({
                messageShowStates: {
                    input: [false, false, false],
                    output: [false, false],
                },
            })
        })

        it('applySearchResults replaces both arrays', () => {
            expectLogic(logic, () => {
                logic.actions.initializeMessageStates(3, 2)
                logic.actions.applySearchResults([true, false, true], [false, true])
            }).toMatchValues({
                messageShowStates: {
                    input: [true, false, true],
                    output: [false, true],
                },
            })
        })
    })

    describe('boolean toggles', () => {
        it('toggleMarkdownRendering toggles the boolean', () => {
            expectLogic(logic).toMatchValues({ isRenderingMarkdown: true })

            expectLogic(logic, () => {
                logic.actions.toggleMarkdownRendering()
            }).toMatchValues({
                isRenderingMarkdown: false,
            })

            expectLogic(logic, () => {
                logic.actions.toggleMarkdownRendering()
            }).toMatchValues({
                isRenderingMarkdown: true,
            })
        })

        it('setIsRenderingMarkdown sets the value directly', () => {
            expectLogic(logic, () => {
                logic.actions.setIsRenderingMarkdown(false)
            }).toMatchValues({
                isRenderingMarkdown: false,
            })
        })

        it('toggleXmlRendering toggles the boolean', () => {
            expectLogic(logic).toMatchValues({ isRenderingXml: false })

            expectLogic(logic, () => {
                logic.actions.toggleXmlRendering()
            }).toMatchValues({
                isRenderingXml: true,
            })

            expectLogic(logic, () => {
                logic.actions.toggleXmlRendering()
            }).toMatchValues({
                isRenderingXml: false,
            })
        })

        it('setIsRenderingXml sets the value directly', () => {
            expectLogic(logic, () => {
                logic.actions.setIsRenderingXml(true)
            }).toMatchValues({
                isRenderingXml: true,
            })
        })

        it('toggleEventTypeExpanded creates entry with false for new type', () => {
            expectLogic(logic, () => {
                logic.actions.toggleEventTypeExpanded('generation')
            }).toMatchValues({
                eventTypeExpandedMap: { generation: false },
            })
        })

        it('toggleEventTypeExpanded toggles existing entry', () => {
            expectLogic(logic, () => {
                logic.actions.toggleEventTypeExpanded('generation')
                logic.actions.toggleEventTypeExpanded('generation')
            }).toMatchValues({
                eventTypeExpandedMap: { generation: true },
            })
        })
    })

    describe('selectors', () => {
        it('hasTrace is false when no data is loaded', () => {
            expectLogic(logic).toMatchValues({ hasTrace: false })
        })

        it('inputMessageShowStates extracts input array', () => {
            expectLogic(logic, () => {
                logic.actions.initializeMessageStates(2, 3)
            }).toMatchValues({
                inputMessageShowStates: [false, false],
            })
        })

        it('outputMessageShowStates extracts output array', () => {
            expectLogic(logic, () => {
                logic.actions.initializeMessageStates(2, 3)
            }).toMatchValues({
                outputMessageShowStates: [true, true, true],
            })
        })

        it('eventTypeExpanded returns true for unknown event types', () => {
            const expanded = logic.values.eventTypeExpanded
            expect(expanded('generation')).toBe(true)
            expect(expanded('span')).toBe(true)
            expect(expanded('unknown')).toBe(true)
        })

        it('eventTypeExpanded respects map values', () => {
            logic.actions.toggleEventTypeExpanded('generation')
            const expanded = logic.values.eventTypeExpanded
            expect(expanded('generation')).toBe(false)
            expect(expanded('span')).toBe(true)
        })
    })

    describe('parseAndLoadTrace listener', () => {
        it('handles empty input', async () => {
            logic.actions.setRawJson('')

            await expectLogic(logic, () => {
                logic.actions.parseAndLoadTrace()
            })
                .toDispatchActions(['parseAndLoadTrace', 'setValidationError', 'setParsedTraceData'])
                .toMatchValues({
                    validationError: null,
                    parsedTraceData: null,
                })
        })

        it('handles whitespace-only input', async () => {
            logic.actions.setRawJson('   ')

            await expectLogic(logic, () => {
                logic.actions.parseAndLoadTrace()
            })
                .toDispatchActions(['parseAndLoadTrace', 'setValidationError', 'setParsedTraceData'])
                .toMatchValues({
                    validationError: null,
                    parsedTraceData: null,
                })
        })

        it('handles invalid JSON syntax', async () => {
            logic.actions.setRawJson('{ invalid json }')

            await expectLogic(logic, () => {
                logic.actions.parseAndLoadTrace()
            })
                .toDispatchActions(['parseAndLoadTrace', 'setValidationError', 'setParsedTraceData'])
                .toMatchValues({
                    parsedTraceData: null,
                })

            expect(logic.values.validationError).toContain('JSON')
        })

        it('handles validation failure - missing trace_id', async () => {
            logic.actions.setRawJson(
                JSON.stringify({
                    timestamp: '2025-01-15T10:00:00Z',
                    events: [{ type: 'generation', name: 'Test' }],
                })
            )

            await expectLogic(logic, () => {
                logic.actions.parseAndLoadTrace()
            })
                .toDispatchActions(['parseAndLoadTrace', 'setValidationError', 'setParsedTraceData'])
                .toMatchValues({
                    validationError: 'Missing or invalid trace_id',
                    parsedTraceData: null,
                })
        })

        it('handles validation failure - missing timestamp', async () => {
            logic.actions.setRawJson(
                JSON.stringify({
                    trace_id: 'test-123',
                    events: [{ type: 'generation', name: 'Test' }],
                })
            )

            await expectLogic(logic, () => {
                logic.actions.parseAndLoadTrace()
            })
                .toDispatchActions(['parseAndLoadTrace', 'setValidationError', 'setParsedTraceData'])
                .toMatchValues({
                    validationError: 'Missing or invalid timestamp',
                    parsedTraceData: null,
                })
        })

        it('handles validation failure - empty events array', async () => {
            logic.actions.setRawJson(
                JSON.stringify({
                    trace_id: 'test-123',
                    timestamp: '2025-01-15T10:00:00Z',
                    events: [],
                })
            )

            await expectLogic(logic, () => {
                logic.actions.parseAndLoadTrace()
            })
                .toDispatchActions(['parseAndLoadTrace', 'setValidationError', 'setParsedTraceData'])
                .toMatchValues({
                    validationError: 'Events array is empty',
                    parsedTraceData: null,
                })
        })

        it('successfully parses valid trace JSON', async () => {
            logic.actions.setRawJson(createValidTraceJson())

            await expectLogic(logic, () => {
                logic.actions.parseAndLoadTrace()
            })
                .toDispatchActions(['parseAndLoadTrace', 'setValidationError', 'setParsedTraceData'])
                .toMatchValues({
                    validationError: null,
                    hasTrace: true,
                })

            expect(logic.values.parsedTraceData).not.toBeNull()
            expect(logic.values.trace?.id).toBe('test-trace-123')
        })

        it('parses trace with optional fields', async () => {
            logic.actions.setRawJson(
                createValidTraceJson({
                    name: 'My Trace',
                    total_cost: 0.05,
                })
            )

            await expectLogic(logic, () => {
                logic.actions.parseAndLoadTrace()
            }).toMatchValues({
                validationError: null,
                hasTrace: true,
            })

            expect(logic.values.trace?.traceName).toBe('My Trace')
            expect(logic.values.trace?.totalCost).toBe(0.05)
        })
    })
})
