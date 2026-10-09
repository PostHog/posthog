import type { Schemas } from '@/api/generated'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

const OPEN_STATUS = 'proposed'
const OPEN_SUGGESTIONS_NOTE =
    'PostHog suggests these changes to this view. Accept one with warehouse-suggestions-accept-prepare, or dismiss it with warehouse-suggestions-dismiss.'

type ViewGetParams = { id: string }
type OpenSuggestion = Pick<Schemas.WarehouseSuggestion, 'id' | 'kind' | 'payload' | 'can_act'>

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
    const openSuggestions = await fetchOpenSuggestions(context, params.id).catch(() => [])
    if (openSuggestions.length === 0) {
        return result
    }
    return { ...(result as object), open_suggestions: openSuggestions, open_suggestions_note: OPEN_SUGGESTIONS_NOTE }
}

export default { afterResponse } satisfies ToolHooks<ViewGetParams>
