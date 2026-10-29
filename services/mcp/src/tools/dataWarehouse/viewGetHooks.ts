import type { Schemas } from '@/api/generated'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

export const SUGGESTIONS_TIMEOUT_MS = 2000
const OPEN_STATUS = 'proposed'
const ACTIONABLE_NOTE =
    'PostHog suggests these changes to this view. Accept one with warehouse-suggestions-accept-prepare, or dismiss it with warehouse-suggestions-dismiss.'
const READ_ONLY_NOTE =
    'PostHog suggests these changes to this view. Accepting or dismissing them needs edit access to the view and an API key with write scope, so share them with someone who has both.'

type ViewGetParams = { id: string }
type OpenSuggestion = Pick<Schemas.WarehouseSuggestion, 'id' | 'kind' | 'payload' | 'can_act'>

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function withinTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(`Timed out after ${timeoutMs}ms`)), timeoutMs)
    })
    try {
        return await Promise.race([promise, timeout])
    } finally {
        clearTimeout(timer)
    }
}

async function fetchOpenSuggestions(context: Context, viewId: string): Promise<OpenSuggestion[]> {
    const projectId = await context.stateManager.getProjectId()
    const page = await context.api.request<Schemas.PaginatedWarehouseSuggestionList>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_suggestions/`,
        query: { subject_id: viewId, status: OPEN_STATUS },
    })
    return (page.results ?? []).map(({ id, kind, payload, can_act }) => ({ id, kind, payload, can_act }))
}

async function afterResponse(context: Context, params: ViewGetParams, result: unknown): Promise<unknown> {
    if (!isRecord(result)) {
        return result
    }
    const openSuggestions = await withinTimeout(fetchOpenSuggestions(context, params.id), SUGGESTIONS_TIMEOUT_MS).catch(
        () => []
    )
    if (openSuggestions.length === 0) {
        return result
    }
    const note = openSuggestions.some((openSuggestion) => openSuggestion.can_act) ? ACTIONABLE_NOTE : READ_ONLY_NOTE
    return { ...result, open_suggestions: openSuggestions, open_suggestions_note: note }
}

export default { afterResponse } satisfies ToolHooks<ViewGetParams>
