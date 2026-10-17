import type { QueryState } from './types'

const noop = (): void => undefined

export function loadingQuery<T>(): QueryState<T> {
    return { data: undefined, isLoading: true, isError: false, error: null, isRefetching: false, refetch: noop }
}

export function errorQuery<T>(error: Error, refetch: () => unknown = noop): QueryState<T> {
    return { data: undefined, isLoading: false, isError: true, error, isRefetching: false, refetch }
}

export function successQuery<T>(
    data: T,
    options: { isRefetching?: boolean; refetch?: () => unknown } = {}
): QueryState<T> {
    return {
        data,
        isLoading: false,
        isError: false,
        error: null,
        isRefetching: options.isRefetching ?? false,
        refetch: options.refetch ?? noop,
    }
}
