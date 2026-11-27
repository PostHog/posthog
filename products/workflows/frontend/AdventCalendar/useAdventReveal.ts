import { useCallback, useEffect, useRef, useState } from 'react'

export type AdventRevealPhase = 'suspense' | 'shown'

const PHASES: [AdventRevealPhase, number][] = [
    ['suspense', 1300],
    ['shown', 1500],
]

export interface AdventRevealState {
    phase: AdventRevealPhase | null
    advance: () => void
}

export function useAdventReveal(doorId: string | null, onDone: () => void): AdventRevealState {
    const [progress, setProgress] = useState({ doorId, step: 0 })
    const done = useRef(onDone)
    done.current = onDone

    const step = progress.doorId === doorId ? Math.min(progress.step, PHASES.length - 1) : 0
    const isLast = step === PHASES.length - 1
    const [phase, duration] = PHASES[step]

    const advance = useCallback((): void => {
        if (!doorId) {
            return
        }
        if (isLast) {
            done.current()
        } else {
            setProgress({ doorId, step: step + 1 })
        }
    }, [doorId, isLast, step])

    useEffect(() => {
        if (!doorId) {
            return
        }
        const timer = window.setTimeout(advance, duration)
        return () => window.clearTimeout(timer)
    }, [doorId, advance, duration])

    return { phase: doorId ? phase : null, advance }
}
