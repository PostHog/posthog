import { apiUrl, projectPath } from '@/api/client'

import type { ChatLinkTarget } from './types'

function projectWebUrl(path: string): string | undefined {
    try {
        return apiUrl(projectPath(path).replace(/^\/api\/projects\//, '/project/'))
    } catch {
        return undefined
    }
}

export function chatLinkUrl(target: ChatLinkTarget, conversationId: string): string | undefined {
    if (target.kind === 'insight') {
        return projectWebUrl(`insights/${encodeURIComponent(target.shortId)}`)
    }
    return projectWebUrl(`ai?chat=${encodeURIComponent(conversationId)}`)
}

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
