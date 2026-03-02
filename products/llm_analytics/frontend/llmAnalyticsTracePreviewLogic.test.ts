import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

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

    it('starts with parse and selection state only', () => {
        expectLogic(logic).toMatchValues({
            rawJson: '',
            parsedTraceData: null,
            validationError: null,
            selectedEventId: null,
            hasTrace: false,
            enrichedTree: [],
            event: null,
        })
    })

    it('loads a valid trace and focuses the first event by default', () => {
        expectLogic(logic, () => {
            logic.actions.setRawJson(createValidTraceJson())
            logic.actions.parseAndLoadTrace()
        }).toMatchValues({
            hasTrace: true,
            validationError: null,
            selectedEventId: null,
            effectiveEventId: 'preview-event-1',
        })

        expect(logic.values.trace?.id).toBe('test-trace-123')
        expect(logic.values.event?.id).toBe('preview-event-1')
    })

    it('resets selectedEventId when a new trace is parsed', () => {
        expectLogic(logic, () => {
            logic.actions.setRawJson(createValidTraceJson())
            logic.actions.parseAndLoadTrace()
            logic.actions.setSelectedEventId('test-trace-123')
            logic.actions.setRawJson(
                createValidTraceJson({
                    trace_id: 'another-trace',
                    events: [{ type: 'span', name: 'Root span' }],
                })
            )
            logic.actions.parseAndLoadTrace()
        }).toMatchValues({
            selectedEventId: null,
            effectiveEventId: 'preview-event-1',
        })

        expect(logic.values.trace?.id).toBe('another-trace')
        expect(logic.values.event?.id).toBe('preview-event-1')
    })

    it('loads top-level trace content even when there are no child events', () => {
        expectLogic(logic, () => {
            logic.actions.setRawJson(
                createValidTraceJson({
                    events: [],
                    input: { prompt: 'Hello' },
                    output: { response: 'Hi' },
                })
            )
            logic.actions.parseAndLoadTrace()
        }).toMatchValues({
            hasTrace: true,
            effectiveEventId: null,
        })

        expect(logic.values.event).toBe(logic.values.trace)
        expect(logic.values.trace?.inputState).toEqual({ prompt: 'Hello' })
        expect(logic.values.trace?.outputState).toEqual({ response: 'Hi' })
    })

    it('reports parse errors and clears loaded trace state', () => {
        expectLogic(logic, () => {
            logic.actions.setRawJson(createValidTraceJson())
            logic.actions.parseAndLoadTrace()
            logic.actions.setSelectedEventId('preview-event-1')
            logic.actions.setRawJson('{ invalid json }')
            logic.actions.parseAndLoadTrace()
        }).toMatchValues({
            hasTrace: false,
            parsedTraceData: null,
            selectedEventId: null,
        })

        expect(logic.values.validationError).toContain('Invalid JSON format')
    })

    it('clearTrace resets preview state', () => {
        expectLogic(logic, () => {
            logic.actions.setRawJson(createValidTraceJson())
            logic.actions.parseAndLoadTrace()
            logic.actions.clearTrace()
        }).toMatchValues({
            rawJson: '',
            parsedTraceData: null,
            validationError: null,
            selectedEventId: null,
            hasTrace: false,
        })
    })
})
