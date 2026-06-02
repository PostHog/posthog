import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { tracingDataLogic } from './tracingDataLogic'
import { tracingSceneLogic } from './tracingSceneLogic'

const TEST_TAB = 'test-tab'

describe('tracingSceneLogic', () => {
    let logic: ReturnType<typeof tracingSceneLogic.build>
    let dataLogic: ReturnType<typeof tracingDataLogic.build>
    let getTraceSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        getTraceSpy = jest.spyOn(api.tracing, 'getTrace').mockResolvedValue({ results: [] } as any)
        logic = tracingSceneLogic({ tabId: TEST_TAB })
        logic.mount()
        dataLogic = tracingDataLogic({ tabId: TEST_TAB })
    })

    afterEach(() => {
        logic?.unmount()
        getTraceSpy.mockRestore()
    })

    describe('openTraceFromLink (deep link)', () => {
        it('opens the trace modal and records the linked span', () => {
            logic.actions.openTraceFromLink('abc123', 'span-9', '2024-01-01T12:00:00.000Z')
            expect(logic.values.selectedTraceId).toEqual('abc123')
            expect(logic.values.linkedSpanId).toEqual('span-9')
            expect(logic.values.isTraceModalOpen).toBe(true)
        })

        it('loads the trace scoped to a window around the timestamp', async () => {
            await expectLogic(dataLogic, () => {
                logic.actions.openTraceFromLink('abc123', undefined, '2024-01-01T12:00:00.000Z')
            }).toDispatchActions(['loadTraceSpans', 'loadTraceSpansSuccess'])

            expect(getTraceSpy).toHaveBeenCalledWith(
                'abc123',
                expect.objectContaining({
                    dateRange: { date_from: '2024-01-01T11:30:00.000Z', date_to: '2024-01-01T12:30:00.000Z' },
                })
            )
        })

        it('clears the linked span when the modal is closed', () => {
            logic.actions.openTraceFromLink('abc123', 'span-9', '2024-01-01T12:00:00.000Z')
            logic.actions.closeTraceModal()
            expect(logic.values.selectedTraceId).toBeNull()
            expect(logic.values.linkedSpanId).toBeNull()
        })
    })
})
