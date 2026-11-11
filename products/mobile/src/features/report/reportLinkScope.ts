import { useMemo } from 'react'

import type { ProjectScope } from '@/api/reports'
import { useAuthStore } from '@/auth/authStore'
import { useSessionProjectScope } from '@/auth/projectScope'
import { useDataMode } from '@/demo/demoMode'

export interface ReportLink {
    projectId: number | null
    host: string | null
}

/**
 * `elsewhere` is a region the session is not signed in to, so no request can reach the report. Otherwise `override`
 * is the project the report screen reads instead of the session's, or null to read the session's project.
 */
export type ReportLinkScope = { kind: 'elsewhere' } | { kind: 'scope'; override: ProjectScope | null }

const SESSION_SCOPE: ReportLinkScope = { kind: 'scope', override: null }

type RouteParams = Record<string, string | string[] | undefined>

/** A repeated query parameter arrives as an array, which the route types do not describe. Such a link is malformed. */
export function routeParam(value: string | string[] | undefined): string | undefined {
    return typeof value === 'string' ? value : undefined
}

export function reportLinkFromParams(params: RouteParams): ReportLink {
    const project = routeParam(params.project)
    const host = routeParam(params.host)
    return {
        projectId: project !== undefined && /^\d+$/.test(project) ? Number(project) : null,
        host: host?.toLowerCase() || null,
    }
}

function hostname(host: string): string {
    return host
        .replace(/^https?:\/\//i, '')
        .replace(/[/:].*$/, '')
        .toLowerCase()
}

export function reportLinkScope(link: ReportLink, session: ProjectScope | null): ReportLinkScope {
    // Signed out, the auth redirect takes over. It keeps the link for after sign-in.
    if (session === null) {
        return SESSION_SCOPE
    }
    if (link.host !== null && hostname(session.host) !== link.host) {
        return { kind: 'elsewhere' }
    }
    if (link.projectId === null || link.projectId === session.projectId) {
        return SESSION_SCOPE
    }
    // The server decides access, so a project missing from the cached project list is still tried.
    return { kind: 'scope', override: { host: session.host, projectId: link.projectId } }
}

/**
 * Moves the session to the link's project, for a screen that reads the session's project instead of the report
 * scope. False means it did not move, because the cached account does not list the project.
 */
export function followLinkProject(projectId: number | null | undefined): boolean {
    if (projectId == null) {
        return true
    }
    if (useAuthStore.getState().projectId !== projectId) {
        useAuthStore.getState().selectProject(projectId, 'link')
    }
    return useAuthStore.getState().projectId === projectId
}

export function useReportLinkScope(link: ReportLink): ReportLinkScope {
    const demo = useDataMode() === 'demo'
    const session = useSessionProjectScope()
    const { projectId, host } = link
    return useMemo(
        () => (demo ? SESSION_SCOPE : reportLinkScope({ projectId, host }, session)),
        [demo, projectId, host, session]
    )
}
