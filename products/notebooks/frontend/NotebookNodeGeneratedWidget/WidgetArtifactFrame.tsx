import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'

import type { WidgetFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

import { createWidgetHostMessageRouter, readWidgetFrame } from './widgetArtifactBridge'

export type WidgetArtifactFrameProps = {
    artifactUrl: string
    title?: string
    allowedFrames: string[]
    onReadFrame: (
        name: string,
        offset: number,
        limit: number,
        runId: string | undefined,
        signal: AbortSignal
    ) => Promise<WidgetFrameApi>
    onArtifactUnavailable?: () => void
    onError?: (message?: string) => void
    onRendered?: () => void
}

export function WidgetArtifactFrame({
    artifactUrl,
    title,
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
        if (renderTimeoutRef.current !== null) {
            window.clearTimeout(renderTimeoutRef.current)
        }
        artifactPortRef.current = port
        const runIds = new Map<string, string>()
        const initialRunIds = new Map<string, Promise<string>>()
        const pageRequests = new Map<string, Promise<WidgetFrameApi>>()
        const route = createWidgetHostMessageRouter(
            (message) => port.postMessage(message),
            () => ({
                onDataRequest: async (_method, payload, signal) =>
                    await readWidgetFrame(
                        latest.current.allowedFrames,
                        async (name, offset, limit, requestSignal) => {
                            let runId = runIds.get(name)
                            const pageKey = (): string => `${name}:${runId ?? 'initial'}:${offset}:${limit}`
                            const cachedPage = pageRequests.get(pageKey())
                            if (cachedPage) {
                                return await cachedPage
                            }
                            const loadPage = async (): Promise<WidgetFrameApi> => {
                                if (!runId) {
                                    const pendingRunId = initialRunIds.get(name)
                                    if (pendingRunId) {
                                        runId = await pendingRunId
                                    } else {
                                        const firstFrame = latest.current.onReadFrame(
                                            name,
                                            offset,
                                            limit,
                                            undefined,
                                            requestSignal
                                        )
                                        const firstRunId = firstFrame.then((frame) => frame.runId)
                                        initialRunIds.set(name, firstRunId)
                                        try {
                                            const frame = await firstFrame
                                            runIds.set(name, frame.runId)
                                            return frame
                                        } finally {
                                            initialRunIds.delete(name)
                                        }
                                    }
                                }
                                const frame = await latest.current.onReadFrame(
                                    name,
                                    offset,
                                    limit,
                                    runId,
                                    requestSignal
                                )
                                runIds.set(name, frame.runId)
                                return frame
                            }
                            const request = loadPage()
                            const initialPageKey = pageKey()
                            pageRequests.set(initialPageKey, request)
                            try {
                                const frame = await request
                                pageRequests.set(`${name}:${frame.runId}:${offset}:${limit}`, Promise.resolve(frame))
                                return frame
                            } catch (error) {
                                pageRequests.delete(initialPageKey)
                                throw error
                            }
                        },
                        payload,
                        signal
                    ),
                onError: (message) => latest.current.onError?.(message),
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
        renderTimeoutRef.current = window.setTimeout(() => latest.current.onArtifactUnavailable?.(), 20_000)
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
            title={title || 'Widget'}
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            className={`w-full h-full border-0 bg-primary ${
                theme === 'dark' ? '[color-scheme:dark]' : '[color-scheme:light]'
            }`}
            onLoad={() => {
                if (hasLoadedRef.current) {
                    clearConnection()
                    latest.current.onArtifactUnavailable?.()
                    return
                }
                hasLoadedRef.current = true
            }}
            onError={() => onArtifactUnavailable?.()}
        />
    )
}
