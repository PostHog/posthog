import type { Context } from '@/tools/types'

/**
 * Optional custom logic around a generated tool's request, declared per tool with
 * `hooks:` in tools.yaml. Methods are declared with method syntax so a hook module can
 * type `params` more narrowly than the generated schema.
 *
 * A hook module default-exports its hooks with `satisfies ToolHooks<...>`, so a misspelled
 * hook name is a compile error instead of a hook that never runs.
 */
export interface ToolHooks<TParams = never> {
    /** Runs before the request. Return the params the request should use. */
    beforeRequest?(context: Context, params: TParams): TParams | Promise<TParams>
    /** Runs after a successful request. Return the result to send to the client. */
    afterResponse?(context: Context, params: TParams, result: unknown): unknown
    /** Runs when the request fails. Return a result to handle the error, or rethrow it to keep it. */
    onError?(context: Context, params: TParams, error: unknown): unknown
}

/**
 * Wraps a generated handler: beforeRequest, then the handler, then afterResponse.
 * A failed beforeRequest aborts before the request is sent and skips onError.
 */
export function withToolHooks<TParams, TResult>(
    hooks: ToolHooks<TParams>,
    handler: (context: Context, params: TParams) => Promise<TResult>
): (context: Context, params: TParams) => Promise<TResult> {
    return async (context, params) => {
        const requestParams = hooks.beforeRequest ? await hooks.beforeRequest(context, params) : params
        let result: TResult
        try {
            result = await handler(context, requestParams)
        } catch (error) {
            if (!hooks.onError) {
                throw error
            }
            // Hooks may return a result the generated type does not describe, such as a "not found" payload.
            return (await hooks.onError(context, requestParams, error)) as TResult
        }
        return hooks.afterResponse ? ((await hooks.afterResponse(context, requestParams, result)) as TResult) : result
    }
}
