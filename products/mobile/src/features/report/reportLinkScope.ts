import { useEffect, useRef } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { type AuthState, useAuthStore } from '@/auth/authStore'
import { useDataMode } from '@/demo/demoMode'

/** The project and host a web report link names. Null fields mean the link did not name them. */
export interface ReportLink {
    projectId: number | null
    host: string | null
}

/**
 * `pending` waits for a project switch or the account load. `elsewhere` is a project or region the session cannot
 * open. `unverified` is a project list the last account load failed to refresh, so the answer is not known yet.
 */
export type ReportLinkScope = 'ready' | 'pending' | 'elsewhere' | 'unverified'

type ScopeAuth = Pick<AuthState, 'status' | 'host' | 'projectId' | 'projects' | 'accountLoading' | 'accountError'>

function hostname(host: string): string {
    return host
        .replace(/^https?:\/\//i, '')
        .replace(/[/:].*$/, '')
        .toLowerCase()
}

export function reportLinkScope(link: ReportLink, auth: ScopeAuth): ReportLinkScope {
    // Signed out, the auth redirect takes over. It keeps the link for after sign-in.
    if (auth.status !== 'signed_in') {
        return 'ready'
    }
    if (link.host !== null && (auth.host === null || hostname(auth.host) !== link.host)) {
        return 'elsewhere'
    }
    if (link.projectId === null || link.projectId === auth.projectId) {
        return 'ready'
    }
    if (auth.projects.some((project) => project.id === link.projectId)) {
        return 'pending'
    }
    // A project created after the cached account loaded appears once the reload finishes.
    if (auth.accountLoading) {
        return 'pending'
    }
    // A failed reload leaves the cached list incomplete, so it cannot rule the project out.
    return auth.accountError !== null ? 'unverified' : 'elsewhere'
}

/** Switches to the link's project before the report loads. The first decided scope holds, so it never switches back. */
export function useReportLinkScope(link: ReportLink): ReportLinkScope {
    const demo = useDataMode() === 'demo'
    const auth = useAuthStore(
        useShallow((state) => ({
            status: state.status,
            host: state.host,
            projectId: state.projectId,
            projects: state.projects,
            accountLoading: state.accountLoading,
            accountError: state.accountError,
        }))
    )
    const settled = useRef<ReportLinkScope | null>(null)
    const scope = demo ? 'ready' : (settled.current ?? reportLinkScope(link, auth))
    const switchTo = scope === 'pending' && auth.projects.some((p) => p.id === link.projectId) ? link.projectId : null

    useEffect(() => {
        if (switchTo !== null) {
            useAuthStore.getState().selectProject(switchTo, 'link')
        }
    }, [switchTo])

    // `pending` and `unverified` both wait on a load, so a later account reload still decides them.
    useEffect(() => {
        if (scope === 'ready' || scope === 'elsewhere') {
            settled.current = scope
        }
    }, [scope])

    return scope
}
