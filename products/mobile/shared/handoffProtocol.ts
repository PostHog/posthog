export const HANDOFF_PARAM = 'ph_mobile_handoff'
export const HANDOFF_FLAG = 'mobile-session-handoff'
const MAX_AGE_MS = 120_000
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function handoffMarker(id: string, now: number): string {
    return `${id}.${now}`
}

export function handoffId(marker: string | null, now: number): string | null {
    if (!marker || marker.length > 51) {
        return null
    }
    const [id, timestamp] = marker.split('.')
    const sentAt = Number(timestamp)
    return id && UUID.test(id) && /^\d{13}$/.test(timestamp ?? '') && sentAt <= now && now - sentAt <= MAX_AGE_MS
        ? id.toLowerCase()
        : null
}

export function takeHandoff(url: URL, now: number): string | null {
    const params = new URLSearchParams(url.hash.slice(1))
    const markers = params.getAll(HANDOFF_PARAM)
    if (markers.length === 0) {
        return null
    }
    params.delete(HANDOFF_PARAM)
    url.hash = params.toString()
    return markers.length === 1 ? handoffId(markers[0] ?? null, now) : null
}

export function isMobileHandoffUrl(url: URL): boolean {
    return (
        ['posthog-dev:', 'posthog-preview:'].includes(url.protocol) &&
        !url.username &&
        !url.password &&
        !url.port &&
        /^(inbox|chats|report|chat|views|settings)(\/|$)/.test(`${url.hostname}${url.pathname}`.replace(/^\/+/, ''))
    )
}
