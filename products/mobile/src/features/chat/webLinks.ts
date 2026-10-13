import { apiUrl } from '@/api/client'

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
