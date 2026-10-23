import { DemoReplay } from './demoReplay'

describe('DemoReplay', () => {
    it('does not start until allowed, deduplicates updates, and stops a pending start immediately', async () => {
        let finish: () => void = () => undefined
        const recorder = {
            startSessionRecording: jest.fn(
                () =>
                    new Promise<void>((resolve) => {
                        finish = resolve
                    })
            ),
            stopSessionRecording: jest.fn().mockResolvedValue(undefined),
        }
        const replay = new DemoReplay(recorder)
        replay.setAllowed(false)
        expect(recorder.startSessionRecording).not.toHaveBeenCalled()
        replay.setAllowed(true)
        replay.setAllowed(true)
        expect(recorder.startSessionRecording).toHaveBeenCalledTimes(1)
        replay.setAllowed(false)
        expect(recorder.stopSessionRecording).toHaveBeenCalledTimes(1)
        finish()
        await Promise.resolve()
        expect(recorder.startSessionRecording).toHaveBeenCalledTimes(1)
    })

    it('stops after a failed start without an unhandled rejection', async () => {
        const recorder = {
            startSessionRecording: jest.fn().mockRejectedValue(new Error('Native plugin unavailable')),
            stopSessionRecording: jest.fn().mockResolvedValue(undefined),
        }
        const replay = new DemoReplay(recorder)
        replay.setAllowed(true)
        await Promise.resolve()
        expect(recorder.stopSessionRecording).toHaveBeenCalledTimes(1)
    })
})
