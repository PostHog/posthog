import type { Context } from '@/tools/types'

interface PromptApiOptions {
    method?: 'GET' | 'POST' | 'PATCH'
    body?: Record<string, unknown>
    query?: Record<string, string>
}

export async function promptFetch<T = unknown>(context: Context, path: string, options?: PromptApiOptions): Promise<T> {
    const projectId = await context.stateManager.getProjectId()
    const basePath = `/api/environments/${projectId}/llm_prompts${path}`

    return context.api.request<T>({
        method: options?.method ?? 'GET',
        path: basePath,
        ...(options?.body ? { body: options.body } : {}),
        ...(options?.query ? { query: options.query } : {}),
    })
}
