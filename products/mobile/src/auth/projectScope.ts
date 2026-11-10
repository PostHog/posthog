import { createContext, useContext, useMemo } from 'react'

import type { ProjectScope } from '@/api/reports'

import { type AuthState, useAuthStore } from './authStore'

function scopeOf(state: Pick<AuthState, 'signedIn' | 'host' | 'projectId'>): ProjectScope | null {
    return state.signedIn && state.host && state.projectId !== null
        ? { host: state.host.replace(/\/$/, ''), projectId: state.projectId }
        : null
}

/** A report a web link opened provides the link's project here, so the session's project stays as it is. */
export const ProjectScopeOverride = createContext<ProjectScope | null>(null)

export function useProjectScopeOverride(): ProjectScope | null {
    return useContext(ProjectScopeOverride)
}

/** The session's project, also inside a `ProjectScopeOverride`. */
export function useSessionProjectScope(): ProjectScope | null {
    const signedIn = useAuthStore((state) => state.signedIn)
    const host = useAuthStore((state) => state.host)
    const projectId = useAuthStore((state) => state.projectId)
    return useMemo(() => scopeOf({ signedIn, host, projectId }), [signedIn, host, projectId])
}

/** The session's project at the moment of the call, for code outside React that follows the session. */
export function sessionProjectScope(): ProjectScope | null {
    return scopeOf(useAuthStore.getState())
}
