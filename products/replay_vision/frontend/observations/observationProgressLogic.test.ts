import { initKeaTests } from '~/test/init'

import { type ObservationProgress } from './observationProgress'
import { observationProgressLogic } from './observationProgressLogic'

const tick = (phase: string, extra: Partial<ObservationProgress> = {}): ObservationProgress => ({
    phase,
    step: 0,
    total_steps: 6,
    ...extra,
})

const rendering = (
    frame: number,
    estimatedTotalFrames: number,
    stage: 'setup' | 'capture' = 'capture'
): ObservationProgress =>
    tick('rendering', { rasterizer: { frame_progress: { phase: stage, frame, estimatedTotalFrames } } })

describe('observationProgressLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('keeps the phase and percent across a remount', () => {
        const first = observationProgressLogic({ observationId: 'obs-1' })
        const unmount = first.mount()
        first.actions.setProgress(tick('fetching'), 1000)
        first.actions.setProgress(tick('analyzing'), 20000)
        first.actions.tick(50000)
        const percent = first.values.percent
        unmount()

        const second = observationProgressLogic({ observationId: 'obs-1' })
        second.mount()
        expect(second.values.displayPhase.label).toEqual('Analyzing recording')
        expect(second.values.percent).toEqual(percent)
    })

    it('forgets a settled observation', () => {
        const first = observationProgressLogic({ observationId: 'obs-2' })
        const unmount = first.mount()
        first.actions.setProgress(tick('analyzing'), 1000)
        first.actions.streamCompleted()
        unmount()

        const second = observationProgressLogic({ observationId: 'obs-2' })
        second.mount()
        expect(second.values.progress).toBeNull()
        expect(second.values.percent).toEqual(0)
    })

    it.each([
        ['a failed query falls back to an earlier phase', [tick('analyzing'), tick('fetching')], 'Analyzing recording'],
        [
            'frame counts start after a long renderer setup',
            [tick('fetching'), rendering(0, 0, 'setup'), rendering(0, 900)],
            'Rendering video',
        ],
        ['a render retry restarts the frame count', [rendering(800, 900), rendering(5, 900)], 'Rendering video'],
    ])('never moves the bar back when %s', (_, ticks, expectedLabel) => {
        const logic = observationProgressLogic({ observationId: `obs-${expectedLabel}-${ticks.length}` })
        logic.mount()
        const percents: number[] = []
        ticks.forEach((progress, i) => {
            logic.actions.setProgress(progress, (i + 1) * 60_000)
            percents.push(logic.values.percent)
        })
        expect(percents).toEqual([...percents].sort((a, b) => a - b))
        expect(logic.values.displayPhase.label).toEqual(expectedLabel)
    })

    it('starts a phase at its server elapsed time, so a late joiner sees the bar already filled', () => {
        const logic = observationProgressLogic({ observationId: 'obs-late' })
        logic.mount()
        logic.actions.setProgress(tick('analyzing', { phase_elapsed_s: 120 }), 1000)
        expect(logic.values.percent).toBeGreaterThan(70)
    })
})
