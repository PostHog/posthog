import { RunStreamFrameBuffer } from './runStreamFrameBuffer'

describe('RunStreamFrameBuffer', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each(['animation frame', 'timeout', 'close', 'hidden tab'])('delivers ordered frames once on %s', (trigger) => {
        const batches: number[][] = []
        const buffer = new RunStreamFrameBuffer<number>((entries) => batches.push(entries))
        if (trigger === 'hidden tab') {
            jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
        }
        if (trigger === 'timeout') {
            jest.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1)
        }
        buffer.push(1)
        buffer.push(2)
        if (trigger === 'close') {
            buffer.flush()
        } else {
            jest.advanceTimersByTime(trigger === 'animation frame' ? 16 : 100)
        }
        expect(batches.flat()).toEqual([1, 2])
        expect(batches).toHaveLength(trigger === 'hidden tab' ? 2 : 1)
        buffer.flush()
        jest.runOnlyPendingTimers()
        expect(batches.flat()).toEqual([1, 2])
    })
})
