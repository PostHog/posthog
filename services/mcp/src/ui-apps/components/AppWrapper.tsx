import type { App } from '@modelcontextprotocol/ext-apps'
import { Maximize2, Minimize2 } from 'lucide-react'
import { type ReactElement, type ReactNode, useCallback, useEffect, useState } from 'react'

import { Button } from '@posthog/quill'

import { useToolResult, type UseToolResultOptions, type UseToolResultReturn } from '../hooks/useToolResult'
import { PostHogLogo } from './PostHogLogo'

export interface AppWrapperProps<T> extends UseToolResultOptions {
    children: (result: UseToolResultReturn<T>) => ReactNode
}

function ExpandButton({
    app,
    onDisplayModeChanged,
}: {
    app: App | null
    onDisplayModeChanged?: () => void
}): ReactElement | null {
    const [supportsFullscreen, setSupportsFullscreen] = useState(false)
    const [isFullscreen, setIsFullscreen] = useState(false)

    useEffect(() => {
        if (!app) {
            return
        }
        const ctx = app.getHostContext()
        const available = ctx?.availableDisplayModes ?? []
        if (available.includes('fullscreen')) {
            setSupportsFullscreen(true)
            setIsFullscreen(ctx?.displayMode === 'fullscreen')
        }
    }, [app])

    const handleToggle = useCallback(() => {
        if (!app) {
            return
        }
        const target = isFullscreen ? 'inline' : 'fullscreen'
        app.requestDisplayMode({ mode: target }).then((result) => {
            setIsFullscreen(result.mode === 'fullscreen')
            // Host needs time to resize the container after the mode switch.
            // Read dimensions immediately, then again after a short delay.
            onDisplayModeChanged?.()
            setTimeout(() => onDisplayModeChanged?.(), 200)
        })
    }, [app, isFullscreen, onDisplayModeChanged])

    if (!supportsFullscreen) {
        return null
    }

    return (
        <Button
            variant="ghost"
            size="icon-xs"
            onClick={handleToggle}
            title={isFullscreen ? 'Exit fullscreen' : 'Expand'}
            aria-label={isFullscreen ? 'Exit fullscreen' : 'Expand'}
        >
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </Button>
    )
}

export function AppWrapper<T>({ children, ...options }: AppWrapperProps<T>): ReactElement {
    const toolResult = useToolResult<T>(options)
    const { data, isConnected, error, isCancelled, openLink, app, containerDimensions, refreshContainerDimensions } =
        toolResult

    const posthogUrl =
        data && typeof data === 'object' && '_posthogUrl' in data
            ? ((data as Record<string, unknown>)._posthogUrl as string | undefined)
            : undefined

    useEffect(() => {
        if (error) {
            console.error('[PostHog MCP App] AppWrapper error:', error.message, error)
        }
    }, [error])

    const hasContent = !error && !isCancelled && isConnected && data

    const rootStyle: React.CSSProperties =
        containerDimensions?.height != null
            ? { height: containerDimensions.height }
            : containerDimensions?.maxHeight != null
              ? { maxHeight: containerDimensions.maxHeight }
              : { minHeight: '100%' }

    if (!hasContent) {
        const showError = error || isCancelled

        return (
            <div
                className="mx-auto flex w-full max-w-[960px] flex-col items-center justify-center gap-3 px-4"
                style={{
                    ...rootStyle,
                    ...(containerDimensions?.height == null ? { minHeight: 200 } : {}),
                }}
            >
                <div className={showError ? '' : '[animation:loading__pulse_4s_ease-in-out_infinite]'}>
                    <PostHogLogo size={40} />
                </div>
                {isCancelled && (
                    <span className="text-xs text-center text-muted-foreground">Tool call was cancelled</span>
                )}
                {error && !isCancelled && (
                    <span className="text-xs text-center text-destructive-foreground">{error.message}</span>
                )}
            </div>
        )
    }

    return (
        <div className="mx-auto flex w-full max-w-[960px] flex-col" style={rootStyle}>
            <div className="overflow-auto">{children(toolResult)}</div>
            <footer className="mt-auto flex items-center justify-between border-t px-3 py-1.5">
                <ExpandButton app={app} onDisplayModeChanged={refreshContainerDimensions} />
                <span className="ml-auto">
                    {posthogUrl ? (
                        <a
                            href={posthogUrl}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => {
                                e.preventDefault()
                                openLink(posthogUrl)
                            }}
                            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                        >
                            <PostHogLogo size={16} />
                            <span>View in PostHog</span>
                        </a>
                    ) : (
                        <PostHogLogo size={16} />
                    )}
                </span>
            </footer>
        </div>
    )
}
