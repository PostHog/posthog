import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'

import type { WidgetFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

import { createWidgetHostMessageRouter, readWidgetFrame } from './widgetArtifactBridge'

export type WidgetArtifactFrameProps = {
    artifactUrl: string
    allowedFrames: string[]
    onReadFrame: (name: string, offset: number, limit: number) => Promise<WidgetFrameApi>
    onArtifactUnavailable?: () => void
    onError?: () => void
    onRendered?: () => void
}

export function WidgetArtifactFrame({
    artifactUrl,
    allowedFrames,
    onReadFrame,
    onArtifactUnavailable,
    onError,
    onRendered,
}: WidgetArtifactFrameProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = isDarkModeOn ? 'dark' : 'light'
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const artifactPortRef = useRef<MessagePort | null>(null)
    const renderTimeoutRef = useRef<number | null>(null)
    const hasLoadedRef = useRef(false)
    const initialTheme = useRef(theme).current
    const latest = useRef({ allowedFrames, onArtifactUnavailable, onError, onReadFrame, onRendered, theme })
    latest.current = { allowedFrames, onArtifactUnavailable, onError, onReadFrame, onRendered, theme }

    const themedArtifactUrl = new URL(artifactUrl)
    themedArtifactUrl.hash = `theme=${initialTheme}`
    const themedArtifactHref = themedArtifactUrl.href

    const clearConnection = (): void => {
        artifactPortRef.current?.close()
        artifactPortRef.current = null
        if (renderTimeoutRef.current !== null) {
            window.clearTimeout(renderTimeoutRef.current)
            renderTimeoutRef.current = null
        }
    }

    const connect = (port: MessagePort): void => {
        artifactPortRef.current = port
        const route = createWidgetHostMessageRouter(
            (message) => port.postMessage(message),
            () => ({
                onDataRequest: (_method, payload) =>
                    readWidgetFrame(latest.current.allowedFrames, latest.current.onReadFrame, payload),
                onError: () => latest.current.onError?.(),
                onRendered: () => {
                    if (renderTimeoutRef.current !== null) {
                        window.clearTimeout(renderTimeoutRef.current)
                        renderTimeoutRef.current = null
                    }
                    latest.current.onRendered?.()
                },
            })
        )
        port.addEventListener('message', (event) => void route(event.data))
        port.start()
        port.postMessage({ channel: 'posthog-canvas', type: 'set-theme', theme: latest.current.theme })
        renderTimeoutRef.current = window.setTimeout(() => latest.current.onArtifactUnavailable?.(), 20_000)
    }

    useEffect(() => {
        clearConnection()
        hasLoadedRef.current = false
        const iframe = iframeRef.current
        if (!iframe?.contentWindow) {
            latest.current.onArtifactUnavailable?.()
            return
        }
        const expectedWindow = iframe.contentWindow
        const receiveNotebookPort = (event: MessageEvent): void => {
            if (
                artifactPortRef.current ||
                event.source !== expectedWindow ||
                event.data?.channel !== 'posthog-canvas' ||
                event.data?.type !== 'notebook-connect' ||
                !event.ports[0]
            ) {
                return
            }
            // The trusted runtime is injected before generated application code. Accepting only its first port
            // prevents a document loaded by a later self-navigation from acquiring the notebook data bridge.
            window.removeEventListener('message', receiveNotebookPort)
            connect(event.ports[0])
        }
        window.addEventListener('message', receiveNotebookPort)
        iframe.src = themedArtifactHref
        return () => {
            window.removeEventListener('message', receiveNotebookPort)
            clearConnection()
        }
    }, [themedArtifactHref])

    useEffect(() => {
        artifactPortRef.current?.postMessage({ channel: 'posthog-canvas', type: 'set-theme', theme })
    }, [theme])

    return (
        <iframe
            ref={iframeRef}
            title="Generated widget"
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            className={`w-full h-full border-0 bg-primary ${
                theme === 'dark' ? '[color-scheme:dark]' : '[color-scheme:light]'
            }`}
            onLoad={() => {
                if (hasLoadedRef.current) {
                    clearConnection()
                    latest.current.onArtifactUnavailable?.()
                }
                hasLoadedRef.current = true
            }}
            onError={() => onArtifactUnavailable?.()}
        />
    )
}
