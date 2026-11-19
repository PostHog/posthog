import { useContext } from 'react'

import type { ProjectScope } from '@/api/reports'

import { ProjectScopeOverride, useSessionProjectScope } from './projectScope'

/** The project a screen reads: the nearest `ProjectScopeOverride`, else the session's project. */
export function useProjectScope(): ProjectScope | null {
    const override = useContext(ProjectScopeOverride)
    const session = useSessionProjectScope()
    return override ?? session
}
