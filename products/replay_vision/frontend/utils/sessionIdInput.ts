// Replay pages that sit directly under /replay/ but are not a recording.
const NON_RECORDING_REPLAY_PATHS = new Set(['home', 'playlists', 'settings', 'file-playback', 'kiosk'])

/**
 * The session ID in what someone pasted: a bare ID, a recording link (`/replay/<id>`), or a replay list link with
 * `sessionRecordingId`. Null when it is a link that points at no recording.
 */
export function sessionIdFromInput(input: string): string | null {
    const trimmed = input.trim()
    if (!trimmed) {
        return null
    }
    if (!trimmed.includes('/')) {
        return trimmed
    }
    let url: URL
    try {
        // The base only matters for a pasted path without a host.
        url = new URL(trimmed, 'https://app.example.com')
    } catch {
        return null
    }
    const fromParam = url.searchParams.get('sessionRecordingId')
    if (fromParam) {
        return fromParam
    }
    const match = url.pathname.match(/\/replay\/([^/]+)\/?$/)
    if (!match || NON_RECORDING_REPLAY_PATHS.has(match[1])) {
        return null
    }
    try {
        return decodeURIComponent(match[1])
    } catch {
        return null
    }
}
