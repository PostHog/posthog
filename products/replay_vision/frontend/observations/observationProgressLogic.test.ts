import { initKeaTests } from '~/test/init'

import { type ObservationProgress, observationProgressLogic } from './observationProgressLogic'

const tick = (step: number): ObservationProgress => ({ phase: 'any', step, total_steps: 6 })

describe('observationProgressLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        ['progress', (logic: ReturnType<typeof observationProgressLogic.build>) => logic.values.progress, tick(2)],
        [
            'phase start times',
            (logic: ReturnType<typeof observationProgressLogic.build>) => logic.values.phaseStartedAt,
            { 1: 1000, 2: 2000 },
        ],
    ])('keeps %s across a remount', (_, read, expected) => {
        const first = observationProgressLogic({ observationId: 'obs-1' })
        const unmount = first.mount()
        first.actions.setProgress(tick(1), 1000)
        first.actions.setProgress(tick(1), 1500)
        first.actions.setProgress(tick(2), 2000)
        unmount()

        const second = observationProgressLogic({ observationId: 'obs-1' })
        second.mount()
        expect(read(second)).toEqual(expected)
    })

    it('forgets a settled observation', () => {
        const first = observationProgressLogic({ observationId: 'obs-2' })
        const unmount = first.mount()
        first.actions.setProgress(tick(3), 1000)
        first.actions.streamCompleted()
        unmount()

        const second = observationProgressLogic({ observationId: 'obs-2' })
        second.mount()
        expect(second.values.progress).toBeNull()
        expect(second.values.phaseStartedAt).toEqual({})
    })
})
