import { Linking } from 'react-native'

import { apiUrl } from '@/api/client'
import { track } from '@/lib/analytics'

// PostHog AI writes app links as paths such as `/project/2/insights/abc`. Only http(s) links open.
export function resolveReplyLink(url: string): string | undefined {
    if (/^https?:\/\//i.test(url)) {
        return url
    }
    if (url.startsWith('/') && !url.startsWith('//')) {
        try {
            return apiUrl(url)
        } catch {
            return undefined
        }
    }
    return undefined
}

export type ReplyLinkSource = 'object_chip' | 'insight_card' | 'query_card' | 'markdown'

/**
 * Opens a link from a reply and sends `mobile_chat_link_opened` once the system accepts it. `objectKind` is a
 * registry kind from `objectKinds.generated.ts`; `appLink` says a markdown link was an app path, not a full URL.
 */
export function openReplyUrl(
    url: string,
    source: ReplyLinkSource,
    detail: { objectKind?: string; appLink?: boolean } = {}
): void {
    Linking.openURL(url)
        .then(() => {
            track('mobile_chat_link_opened', {
                source,
                object_kind: detail.objectKind ?? null,
                app_link: detail.appLink,
            })
        })
        .catch(() => undefined)
}
