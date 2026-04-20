import { useCallback, useEffect, useRef } from 'react'

// Call callback once per dependency change
export function useCallbackOnce<F extends (...args: any[]) => any>(cb: F, deps: any[]): (...args: any[]) => void {
    const called = useRef(false)

    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => {
        called.current = false
    }, deps)

    return useCallback(
        (...args: any[]) => {
            if (!called.current) {
                cb(...args)
                called.current = true
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        []
    )
}
