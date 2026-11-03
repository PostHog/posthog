import { HANDOFF_FLAG, HANDOFF_PARAM, handoffMarker, isMobileHandoffUrl, takeHandoff } from './handoffProtocol'

interface HandoffClient {
    capture: (event: string, properties: Record<string, string>) => unknown
    isFeatureEnabled: (key: string) => boolean | undefined
    onFeatureFlags: (callback: () => void) => () => void
}

export function consumeMobileHandoff(): string | null {
    const url = new URL(window.location.href)
    const id = takeHandoff(url, Date.now())
    if (url.href !== window.location.href) {
        window.history.replaceState(window.history.state, '', url.href)
    }
    return id
}

export function installMobileHandoff(client: HandoffClient, incomingId: string | null): () => void {
    const receive = (): void => {
        if (incomingId && client.isFeatureEnabled(HANDOFF_FLAG)) {
            client.capture('web_session_handoff_received', {
                handoff_id: incomingId,
                session_continuity: 'correlated',
            })
            incomingId = null
        }
    }
    receive()
    const unsubscribe = client.onFeatureFlags(receive)
    const onClick = (event: MouseEvent): void => {
        if (
            event.defaultPrevented ||
            event.button !== 0 ||
            !window.crypto.randomUUID ||
            !client.isFeatureEnabled(HANDOFF_FLAG)
        ) {
            return
        }
        const anchor = event.target instanceof Element ? event.target.closest('a[href]') : null
        if (!(anchor instanceof HTMLAnchorElement)) {
            return
        }
        let url: URL
        try {
            url = new URL(anchor.href)
        } catch {
            return
        }
        if (!isMobileHandoffUrl(url)) {
            return
        }
        takeHandoff(url, Date.now())
        if (url.hash) {
            return
        }
        const id = window.crypto.randomUUID()
        url.hash = new URLSearchParams({ [HANDOFF_PARAM]: handoffMarker(id, Date.now()) }).toString()
        anchor.href = url.href
        client.capture('web_session_handoff_started', { handoff_id: id, session_continuity: 'correlated' })
    }
    document.addEventListener('click', onClick)
    return () => {
        unsubscribe()
        document.removeEventListener('click', onClick)
    }
}
