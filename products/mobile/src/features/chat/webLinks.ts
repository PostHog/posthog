import { apiUrl } from '@/api/client'
import { type AnalyticsProperties, track } from '@/lib/analytics'
import { openPostHogUrl } from '@/lib/sessionHandoff'

// PostHog AI writes app links as paths such as `/project/2/insights/abc`. Only http(s) links open.
export function resolveReplyLink(url: string, projectUrl?: string): string | undefined {
    if (/^https?:\/\//i.test(url)) {
        return url
    }
    if (url.startsWith('/') && !url.startsWith('//')) {
        try {
            if (projectUrl) {
                return /^\/(?:project|organization)(?:\/|$)/.test(url)
                    ? new URL(url, projectUrl).toString()
                    : `${projectUrl}${url}`
            }
            return apiUrl(url)
        } catch {
            return undefined
        }
    }
    return undefined
}

export type ReplyLinkSource = 'object_chip' | 'insight_card' | 'query_card' | 'markdown'

function openChatUrl(url: string, properties: AnalyticsProperties): void {
    openPostHogUrl(url)
        .then(() => track('mobile_chat_link_opened', properties))
        .catch(() => undefined)
}

export function openUserMessageUrl(url: string): void {
    openChatUrl(url, { source: 'user_message' })
}

/**
 * Opens a link from a reply and sends `mobile_chat_link_opened` once the system accepts it. `objectKind` is a
 * registry kind from `objectKinds.generated.ts`; `appLink` says a markdown link was an app path, not a full URL.
 */
export function openReplyUrl(
    url: string,
    source: ReplyLinkSource,
    detail: { objectKind?: string; appLink?: boolean } = {}
): void {
    openChatUrl(url, {
        source,
        object_kind: detail.objectKind ?? null,
        app_link: detail.appLink,
    })
}
