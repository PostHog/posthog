import type { ProjectScope } from '@/api/reports'

/** The web player for one session, at `seconds` into it when given. Undefined without a project (demo). */
export function sessionWebUrl(
    scope: ProjectScope | null,
    sessionId: string,
    seconds?: number | null
): string | undefined {
    if (!scope) {
        return undefined
    }
    const base = `${scope.host}/project/${scope.projectId}/replay/${encodeURIComponent(sessionId)}`
    return typeof seconds === 'number' && seconds > 0 ? `${base}?t=${Math.floor(seconds)}` : base
}

export function parseSeekSeconds(value: string | string[] | undefined): number | undefined {
    const raw = Array.isArray(value) ? value[0] : value
    if (raw === undefined || raw.trim() === '') {
        return undefined
    }
    const seconds = Number(raw)
    return Number.isFinite(seconds) && seconds >= 0 ? Math.floor(seconds) : undefined
}

/**
 * The moment a share or the web player opens at: the time the link or report named, which is what the person came to
 * see, else the scan's key moment, else the start.
 */
export function shareSeconds(keyMomentMs: number | null, t: number | undefined): number {
    if (t !== undefined) {
        return t
    }
    return keyMomentMs !== null ? Math.floor(keyMomentMs / 1000) : 0
}

export type SessionOpenSource = 'report' | 'chart' | 'issue' | 'list' | 'link' | 'other'

const SOURCES: readonly SessionOpenSource[] = ['report', 'chart', 'issue', 'list', 'link', 'other']

export function sessionOpenSource(value: string | string[] | undefined): SessionOpenSource {
    const raw = Array.isArray(value) ? value[0] : value
    return SOURCES.find((source) => source === raw) ?? 'other'
}
