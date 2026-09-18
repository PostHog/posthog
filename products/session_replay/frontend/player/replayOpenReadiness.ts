import { CustomerJourney } from 'lib/customerJourneys/createCustomerJourney'

export function observeReplayOpenReadiness(
    journey: CustomerJourney,
    readState: () => { player: object | null; canPresent: boolean },
    frames = {
        requestFrame: (callback: FrameRequestCallback): number => requestAnimationFrame(callback),
        cancelFrame: (id: number): void => cancelAnimationFrame(id),
    }
): {
    rebuilt: (player: object) => void
    positioned: (player: object) => void
    reset: () => void
    presentationChanged: () => void
    dispose: () => void
} {
    let reconstructed: object | null = null
    let positioned: object | null = null
    let frameId: number | undefined
    let stopped = false

    const cancelPendingFrame = (): void => {
        if (frameId !== undefined) {
            frames.cancelFrame(frameId)
            frameId = undefined
        }
    }
    const reset = (): void => {
        reconstructed = null
        positioned = null
        cancelPendingFrame()
    }
    const schedule = (): void => {
        const candidate = reconstructed
        if (stopped || !candidate || candidate !== positioned || frameId !== undefined) {
            return
        }
        const stillReady = (): boolean => {
            const state = readState()
            return !stopped && state.player === candidate && state.canPresent && reconstructed === candidate
        }
        // A callback runs before painting. A second frame allows one presentation opportunity;
        // this measures the reconstructed frame, not completion of all recorded assets.
        frameId = frames.requestFrame(() => {
            frameId = undefined
            if (!stillReady()) {
                return
            }
            frameId = frames.requestFrame(() => {
                frameId = undefined
                if (stillReady()) {
                    stopped = true
                    journey.firstUseful()
                    journey.finish('usable')
                    reset()
                }
            })
        })
    }
    return {
        rebuilt: (player) => {
            if (!stopped && player === readState().player) {
                reconstructed = player
                schedule()
            }
        },
        positioned: (player) => {
            if (!stopped && player === readState().player) {
                positioned = player
                schedule()
            }
        },
        reset,
        presentationChanged: () => {
            cancelPendingFrame()
            schedule()
        },
        dispose: () => {
            stopped = true
            reset()
        },
    }
}
