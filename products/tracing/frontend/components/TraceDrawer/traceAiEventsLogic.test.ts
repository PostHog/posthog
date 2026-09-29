import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { tracingSpansTraceAiEventsRetrieve } from 'products/tracing/frontend/generated/api'

import { traceAiEventsLogic, TraceAiEventsLogicProps } from './traceAiEventsLogic'

jest.mock('products/tracing/frontend/generated/api', () => ({
    tracingSpansTraceAiEventsRetrieve: jest.fn(),
}))

const mockAiEventsRetrieve = tracingSpansTraceAiEventsRetrieve as jest.MockedFunction<
    typeof tracingSpansTraceAiEventsRetrieve
>

// Spans read their ids back as uppercase hex, while the SDKs write them lowercase.
const PROPS: TraceAiEventsLogicProps = {
    traceId: '4BF92F3577B34DA6A3CE929D0E0E4736',
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
        mockAiEventsRetrieve.mockReset()
        mockAiEventsRetrieve.mockResolvedValue({ results: [], has_more: false, limit: 500 })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('asks for the events of the trace by its lowercase id and keeps the cap marker', async () => {
        mockAiEventsRetrieve.mockResolvedValue({ results: [], has_more: true, limit: 500 })
        await mount()

        expect(mockAiEventsRetrieve).toHaveBeenCalledTimes(1)
        expect(mockAiEventsRetrieve.mock.calls[0][1]).toBe(PROPS.traceId!.toLowerCase())
        expect(logic.values.hasMoreAiEvents).toBe(true)
    })

    // On a cold page load the flag can arrive from posthog-js after the trace has loaded.
    it('fetches once the flag turns on after mount', async () => {
        await mount({}, false)

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_AI_EVENTS]: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAiEventsRetrieve).toHaveBeenCalledTimes(1)
    })

    // The endpoint must stay uncalled while the flag is off, and for an all-zero id, which is
    // OpenTelemetry's "no id" sentinel.
    it.each([
        ['the flag off', {}, false],
        ['an all-zero trace id', { traceId: '0'.repeat(32) }, true],
    ])('fetches nothing with %s', async (_name, props, flagOn) => {
        await mount(props, flagOn)

        expect(mockAiEventsRetrieve).not.toHaveBeenCalled()
        expect(logic.values.aiEvents).toEqual([])
    })
})
