import type { Context } from '@/tools/types'

/** Adds a _posthogUrl field to any type. Use instead of `T & { _posthogUrl: string }`. */
export type WithPostHogUrl<T = unknown> = T & { _posthogUrl: string }

/** Adds _posthogUrl to a result object. */
export async function withPostHogUrl<T>(context: Context, result: T, path: string): Promise<WithPostHogUrl<T>> {
    const projectId = await context.stateManager.getProjectId()

    const baseUrl = context.api.getProjectBaseUrl(projectId)
    const fullUrl = `${baseUrl}${path}`

    return { ...result, _posthogUrl: fullUrl } as WithPostHogUrl<T>
}
