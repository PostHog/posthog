import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { tracingSpansTraceAiEventsCreate } from 'products/tracing/frontend/generated/api'

import { traceAiEventsLogic, TraceAiEventsLogicProps } from './traceAiEventsLogic'

jest.mock('products/tracing/frontend/generated/api', () => ({
    tracingSpansTraceAiEventsCreate: jest.fn(),
}))

const mockAiEventsCreate = tracingSpansTraceAiEventsCreate as jest.MockedFunction<
    typeof tracingSpansTraceAiEventsCreate
>

// Spans read their ids back as uppercase hex, while the SDKs write them lowercase.
const PROPS: TraceAiEventsLogicProps = {
    traceId: '4BF92F3577B34DA6A3CE929D0E0E4736',
    timestamp: '2026-06-02T08:00:00Z',
    endTimestamp: '2026-06-02T09:30:00Z',
}

describe('traceAiEventsLogic', () => {
    let logic: ReturnType<typeof traceAiEventsLogic.build>

    const mount = async (props: Partial<TraceAiEventsLogicProps> = {}, flagOn = true): Promise<void> => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_AI_EVENTS]: flagOn })
        logic = traceAiEventsLogic({ ...PROPS, ...props })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        mockAiEventsCreate.mockReset()
        mockAiEventsCreate.mockResolvedValue({ results: [] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    // A window bounded only by the trace start misses the last calls of a run that outlives the
    // margin, and a window that drifts from the trace's own lookup misses its first ones.
    it('asks for the events an hour either side of the loaded trace', async () => {
        await mount()

        expect(mockAiEventsCreate).toHaveBeenCalledTimes(1)
        expect(mockAiEventsCreate.mock.calls[0].slice(1)).toEqual([
            PROPS.traceId!.toLowerCase(),
            { dateFrom: '2026-06-02T07:00:00.000Z', dateTo: '2026-06-02T10:30:00.000Z' },
        ])
    })

    // The endpoint must stay uncalled while the flag is off, before the trace has loaded, and
    // for an all-zero id, which is OpenTelemetry's "no id" sentinel.
    it.each([
        ['the flag off', {}, false],
        ['no trace start', { timestamp: null }, true],
        ['an all-zero trace id', { traceId: '0'.repeat(32) }, true],
    ])('fetches nothing with %s', async (_name, props, flagOn) => {
        await mount(props, flagOn)

        expect(mockAiEventsCreate).not.toHaveBeenCalled()
        expect(logic.values.aiEvents).toEqual([])
    })
})
