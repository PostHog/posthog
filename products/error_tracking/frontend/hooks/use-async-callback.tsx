import { useDebouncedCallback } from 'node_modules/use-debounce/dist'
import { useCallback, useRef, useState } from 'react'

type AsyncCallbackType<U, T extends (...args: any[]) => Promise<U>> = ((...args: Parameters<T>) => void) & {
    isPending: () => boolean
    isRejected: () => boolean
}

export function useAsyncCallback<U, T extends (...args: any[]) => Promise<U>>(
    callback: T,
    deps: React.DependencyList = [],
    options: { delay?: number; onDone?: (res: U) => void } = { delay: 0, onDone: undefined }
): AsyncCallbackType<U, T> {
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<Error | null>(null)

    const callbackRef = useRef(callback)
    callbackRef.current = callback

    const execute = useCallback(
        async (...args: Parameters<T>): Promise<U | undefined> => {
            setLoading(true)
            setError(null)
            try {
                let res = await callbackRef.current(...args)
                options.onDone?.(res)
                return res
            } catch (err) {
                setError(err as Error)
            } finally {
                setLoading(false)
            }
        },
        [...deps, options.onDone, options]
    )
    const executeDebounced = useDebouncedCallback(execute, options.delay)
    const executeAsync = function (...args: Parameters<T>): void {
        setLoading(true)
        executeDebounced(...args)
    }
    executeAsync.isPending = () => executeDebounced.isPending() || loading
    executeAsync.isRejected = () => error !== null
    return executeAsync
}
