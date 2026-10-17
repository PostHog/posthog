import { useCallback, useRef, useState } from 'react'

export interface AsyncAction<Args extends unknown[]> {
    run: (...args: Args) => Promise<void>
    pending: boolean
}

// A second call while one is in flight is ignored, which guards against double taps.
export function useAsyncAction<Args extends unknown[]>(fn: (...args: Args) => Promise<void> | void): AsyncAction<Args> {
    const [pending, setPending] = useState(false)
    const inFlight = useRef(false)
    const fnRef = useRef(fn)
    fnRef.current = fn
    const run = useCallback(async (...args: Args): Promise<void> => {
        if (inFlight.current) {
            return
        }
        inFlight.current = true
        setPending(true)
        try {
            await fnRef.current(...args)
        } finally {
            inFlight.current = false
            setPending(false)
        }
    }, [])
    return { run, pending }
}
