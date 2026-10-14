import { useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'

import type { ProjectScope } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { type DataMode, useDataMode } from '@/demo/demoMode'

import type { ItemContext } from './items'
import { useViewsAccess, type ViewsAccess } from './useViewsAccess'

export interface ViewsContext {
    mode: DataMode
    /** Null in demo mode, so demo cache entries never mix with a project's. */
    scope: ProjectScope | null
    access: ViewsAccess
    /** Demo mode, or live with a project and the Views scopes. Nothing loads otherwise. */
    ready: boolean
    item: ItemContext
}

export function useViewsContext(): ViewsContext {
    const mode = useDataMode()
    const projectScope = useProjectScope()
    const client = useQueryClient()
    const access = useViewsAccess()
    const demo = mode === 'demo'
    const scope = demo ? null : projectScope
    const item = useMemo<ItemContext>(() => ({ client, scope, demo }), [client, scope, demo])
    const ready = demo || (mode === 'live' && scope !== null && access.state === 'ok')
    return { mode, scope, access, ready, item }
}
