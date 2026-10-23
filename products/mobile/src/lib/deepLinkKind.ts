export type DeepLinkKind =
    | 'inbox'
    | 'chats'
    | 'report'
    | 'views'
    | 'chat'
    | 'settings'
    | 'sign_in'
    | 'callback'
    | 'other'

const KINDS: Record<string, DeepLinkKind> = {
    inbox: 'inbox',
    chats: 'chats',
    report: 'report',
    views: 'views',
    chat: 'chat',
    settings: 'settings',
    'sign-in': 'sign_in',
    callback: 'callback',
}

/**
 * The first path segment of an incoming link as a fixed enum, so analytics never carries the path itself. Null for
 * the app's root URL, which Expo Router also passes on a cold start without a link.
 */
export function deepLinkKind(path: string): DeepLinkKind | null {
    // `posthog://inbox` puts the screen where a host would be. An http(s) link has a real host, which is dropped.
    const withoutScheme = path.replace(/^https?:\/\/[^/?#]*/i, '').replace(/^[a-z][a-z0-9+.-]*:\/\//i, '')
    const first = withoutScheme.replace(/^\/+/, '').split(/[/?#]/, 1)[0] ?? ''
    if (first === '') {
        return null
    }
    return KINDS[first] ?? 'other'
}
