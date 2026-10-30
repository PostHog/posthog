export type DeepLinkKind =
    | 'inbox'
    | 'chats'
    | 'report'
    | 'views'
    | 'chat'
    | 'settings'
    | 'sign_in'
    | 'callback'
    | 'error_tracking'
    | 'replay'
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
    errors: 'error_tracking',
    error_tracking: 'error_tracking',
    'error-tracking': 'error_tracking',
    replay: 'replay',
}

const PROJECT_KINDS: Record<string, DeepLinkKind> = {
    error_tracking: 'error_tracking',
    'error-tracking': 'error_tracking',
    replay: 'replay',
}

// `posthog://inbox` puts the screen where a host would be. An http(s) link has a real host, which is dropped.
function withoutOrigin(path: string): string {
    return path.replace(/^https?:\/\/[^/?#]*/i, '').replace(/^[a-z][a-z0-9+.-]*:\/\//i, '')
}

interface LinkParts {
    segments: string[]
    web: boolean
    query: string
}

function linkParts(path: string): LinkParts {
    const rest = withoutOrigin(path)
    const queryStart = rest.search(/[?#]/)
    const pathname = queryStart === -1 ? rest : rest.slice(0, queryStart)
    const query = queryStart === -1 || rest[queryStart] !== '?' ? '' : rest.slice(queryStart + 1).split('#', 1)[0]
    const segments = pathname.split('/').filter(Boolean)
    const projectLink = segments[0] === 'project' && segments[1] !== undefined && /^\d+$/.test(segments[1])
    if (projectLink) {
        segments.splice(0, 2)
    }
    return { segments, web: projectLink || /^https?:/i.test(path), query: query ?? '' }
}

/**
 * The first path segment of an incoming link as a fixed enum, so analytics never carries the path itself. A web link's
 * `project/{id}` prefix is skipped. Null for the app's root URL, which Expo Router also passes on a cold start without
 * a link.
 */
export function deepLinkKind(path: string): DeepLinkKind | null {
    const { segments } = linkParts(path)
    const projectLink = /^\/*project\/\d+/.test(withoutOrigin(path))
    const first = segments[0]
    if (first === undefined) {
        return projectLink ? 'other' : null
    }
    return (projectLink ? PROJECT_KINDS[first] : KINDS[first]) ?? 'other'
}

function queryParam(query: string, name: string): string | null {
    for (const pair of query.split('&')) {
        const [key, value = ''] = pair.split('=')
        if (key === name) {
            try {
                return decodeURIComponent(value.replace(/\+/g, ' '))
            } catch {
                return null
            }
        }
    }
    return null
}

const ERROR_TRACKING_PAGES = new Set([
    'configuration',
    'settings',
    'symbol_sets',
    'symbol-sets',
    'fingerprint',
    'alerts',
])
const REPLAY_PAGES = new Set(['home', 'playlists', 'settings', 'file-playback', 'kiosk'])
const SAFE_ID = /^[\w-]+$/

function sessionPath(sessionId: string, query: string): string {
    const t = queryParam(query, 't')
    const seconds = t !== null && /^\d+$/.test(t) ? t : null
    return seconds === null ? `/replay/${sessionId}?source=link` : `/replay/${sessionId}?source=link&t=${seconds}`
}

export function webLinkTarget(path: string): string | null {
    const { segments, web, query } = linkParts(path)
    const [section, id, ...more] = segments
    if (!web || more.length > 0 || (id !== undefined && !SAFE_ID.test(id))) {
        return null
    }
    if (section === 'error_tracking' || section === 'error-tracking') {
        if (id === undefined) {
            return '/errors'
        }
        return ERROR_TRACKING_PAGES.has(id) ? null : `/errors/${id}?from=link`
    }
    if (section === 'replay') {
        if (id === undefined || id === 'home') {
            const sessionId = queryParam(query, 'sessionRecordingId')
            if (sessionId !== null && SAFE_ID.test(sessionId)) {
                return sessionPath(sessionId, query)
            }
            return '/replay'
        }
        return REPLAY_PAGES.has(id) ? null : sessionPath(id, query)
    }
    return null
}
