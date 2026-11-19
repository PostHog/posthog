import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

type FindGroupParams = { skip_create_notebook?: boolean }

// The find endpoint creates a notebook unless this is true, and groups-find needs only group:read.
function beforeRequest<T extends FindGroupParams>(_context: Context, params: T): T {
    return { ...params, skip_create_notebook: true }
}

export default { beforeRequest } satisfies ToolHooks<FindGroupParams>
