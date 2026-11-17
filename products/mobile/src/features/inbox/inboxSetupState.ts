import type { InboxStatusApi } from '@/api/inboxStatus'
import type { ProjectScope } from '@/api/reports'
import { appScheme, isInternalBuild, isLoopbackHost } from '@/lib/environment'

export type InboxEmptyKind =
    | 'not_started'
    | 'in_progress'
    | 'paused'
    | 'ai_disabled'
    | 'pending'
    | 'running'
    | 'no_data'
    | 'insufficient_data'
    | 'no_actionable_finding'
    | 'incomplete'
    | 'waiting'
    | 'quiet'

export function inboxEmptyKind(status: InboxStatusApi): InboxEmptyKind {
    if (status.setup_state !== 'active') return status.setup_state
    if (status.has_report_history || status.first_report_status === 'report_created') return 'quiet'
    return status.first_report_status ?? 'waiting'
}

export function inboxSetupUrl(scope: ProjectScope | null, kind: InboxEmptyKind | 'unavailable'): string | null {
    if (!scope) return null
    try {
        const host = new URL(scope.host)
        if (
            (host.protocol !== 'https:' &&
                !(isInternalBuild && host.protocol === 'http:' && isLoopbackHost(host.hostname))) ||
            host.username ||
            host.password
        )
            return null
        const path =
            kind === 'not_started' || kind === 'in_progress'
                ? 'inbox/activate'
                : kind === 'ai_disabled'
                  ? 'settings/organization-details'
                  : kind === 'unavailable'
                    ? 'inbox'
                    : 'inbox/settings'
        const url = new URL(`/project/${scope.projectId}/${path}`, host.origin)
        if (path === 'inbox/activate') url.searchParams.set('mobile_return', appScheme)
        url.searchParams.set('utm_source', 'posthog_mobile')
        if (kind === 'ai_disabled') url.hash = 'organization-ai-consent'
        return url.toString()
    } catch {
        return null
    }
}
