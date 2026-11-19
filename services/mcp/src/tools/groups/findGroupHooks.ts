import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

type FindGroupParams = { skip_create_notebook?: boolean }

// groups-find needs only group:read, but the find endpoint creates a CRM notebook unless
// skip_create_notebook is true. Forcing it keeps the tool read-only whatever the caller passes.
function beforeRequest<T extends FindGroupParams>(_context: Context, params: T): T {
    return { ...params, skip_create_notebook: true }
}

export default { beforeRequest } satisfies ToolHooks<FindGroupParams>
