import type { App } from '@modelcontextprotocol/ext-apps'
import { type ReactElement, type ReactNode, useCallback, useEffect, useState } from 'react'

import { Link } from '@posthog/mosaic'

import { useToolResult, type UseToolResultOptions, type UseToolResultReturn } from '../hooks/useToolResult'

export interface AppWrapperProps<T> extends UseToolResultOptions {
    children: (result: UseToolResultReturn<T>) => ReactNode
}

function PostHogLogo({ size = 16 }: { size?: number }): ReactElement {
    return (
        <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
                d="M8.35523 16.1353C8.14021 16.5654 7.52647 16.5654 7.31142 16.1353L6.79714 15.1068C6.715 14.9425 6.715 14.7491 6.79714 14.5849L7.31142 13.5563C7.52647 13.1262 8.14021 13.1262 8.35523 13.5563L8.86953 14.5849C8.95163 14.7491 8.95163 14.9425 8.86953 15.1068L8.35523 16.1353ZM8.35523 21.9687C8.14021 22.3988 7.52647 22.3988 7.31142 21.9687L6.79714 20.9401C6.715 20.7758 6.715 20.5825 6.79714 20.4182L7.31142 19.3897C7.52647 18.9596 8.14021 18.9596 8.35523 19.3897L8.86953 20.4182C8.95163 20.5825 8.95163 20.7758 8.86953 20.9401L8.35523 21.9687Z"
                fill="#1D4AFF"
            />
            <path
                d="M2 19.7545C2 19.2347 2.62852 18.9743 2.99611 19.3419L5.67055 22.0164C6.03815 22.384 5.7778 23.0125 5.25796 23.0125H2.58351C2.26125 23.0125 2 22.7512 2 22.429V19.7545ZM2 16.9375C2 17.0922 2.06148 17.2407 2.17091 17.3501L7.66243 22.8416C7.77186 22.951 7.92028 23.0125 8.07502 23.0125H11.0913C11.6111 23.0125 11.8715 22.384 11.5039 22.0164L2.99611 13.5086C2.62852 13.141 2 13.4013 2 13.9212V16.9375V16.9375ZM2 11.1041C2 11.2589 2.06148 11.4073 2.17091 11.5167L13.4958 22.8416C13.6052 22.951 13.7536 23.0125 13.9084 23.0125H16.9246C17.4445 23.0125 17.7048 22.384 17.3372 22.0164L2.99611 7.67526C2.62853 7.30767 2 7.56801 2 8.08786V11.1041V11.1041ZM7.83333 11.1041C7.83333 11.2589 7.89484 11.4073 8.00424 11.5167L18.5039 22.0164C18.8715 22.384 19.5 22.1236 19.5 21.6038V18.5875C19.5 18.4328 19.4385 18.2843 19.3291 18.1749L8.82944 7.67525C8.46183 7.30767 7.83333 7.56801 7.83333 8.08786V11.1041ZM14.6628 7.67526C14.2952 7.30767 13.6667 7.56801 13.6667 8.08786V11.1041C13.6667 11.2589 13.7282 11.4073 13.8376 11.5167L18.5039 16.183C18.8715 16.5507 19.5 16.2903 19.5 15.7704V12.7542C19.5 12.5994 19.4385 12.451 19.3291 12.3416L14.6628 7.67526V7.67526Z"
                fill="#F9BD2B"
            />
            <path
                d="M26.8136 19.8261L21.3212 14.3337C20.9536 13.966 20.3251 14.2264 20.3251 14.7463V22.429C20.3251 22.7512 20.5863 23.0125 20.9086 23.0125H29.4165C29.7388 23.0125 30 22.7512 30 22.429V21.7293C30 21.4071 29.7377 21.1497 29.4181 21.1081C28.4374 20.9804 27.52 20.5325 26.8136 19.8261ZM23.125 21.1458C22.6099 21.1458 22.1917 20.7277 22.1917 20.2125C22.1917 19.6973 22.6099 19.2791 23.125 19.2791C23.6403 19.2791 24.0584 19.6973 24.0584 20.2125C24.0584 20.7277 23.6403 21.1458 23.125 21.1458Z"
                fill="black"
            />
            <path
                d="M2 22.429C2 22.7512 2.26125 23.0125 2.58351 23.0125H5.25796C5.7778 23.0125 6.03815 22.384 5.67056 22.0164L2.99611 19.3419C2.62852 18.9743 2 19.2347 2 19.7545V22.429V22.429ZM7.83333 12.5125L2.99611 7.67526C2.62852 7.30767 2 7.56801 2 8.08786V11.1041C2 11.2589 2.06148 11.4073 2.17091 11.5167L7.83333 17.1791V12.5125ZM2.99611 13.5086C2.62852 13.141 2 13.4013 2 13.9212V16.9375C2 17.0922 2.06148 17.2406 2.17091 17.3501L7.83333 23.0125V18.3458L2.99611 13.5086V13.5086Z"
                fill="#1D4AFF"
            />
            <path
                d="M13.6667 12.7542C13.6667 12.5994 13.6052 12.451 13.4958 12.3416L8.82944 7.67526C8.46189 7.30767 7.83334 7.56801 7.83334 8.08786V11.1041C7.83334 11.2589 7.89484 11.4073 8.00424 11.5167L13.6667 17.1791V12.7542V12.7542ZM7.83334 23.0125H11.0913C11.6111 23.0125 11.8715 22.384 11.5039 22.0164L7.83334 18.3458V23.0125ZM7.83334 12.5125V16.9375C7.83334 17.0922 7.89484 17.2406 8.00424 17.3501L13.6667 23.0125V18.5875C13.6667 18.4328 13.6052 18.2843 13.4958 18.1749L7.83334 12.5125Z"
                fill="#F54E00"
            />
        </svg>
    )
}

export function AppErrorState({ message }: { message: string }): ReactElement {
    useEffect(() => {
        console.error('[PostHog MCP App] AppErrorState:', message)
    }, [message])

    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: 200,
                gap: '0.75rem',
            }}
        >
            <PostHogLogo size={40} />
            <span style={{ color: 'var(--color-text-danger, #dc2626)', fontSize: '0.8125rem' }}>{message}</span>
        </div>
    )
}

export function AppLoadingState(): ReactElement {
    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: 200,
            }}
        >
            <div style={{ animation: 'loading__pulse 2s ease-in-out infinite' }}>
                <PostHogLogo size={40} />
            </div>
        </div>
    )
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
        <button
            onClick={handleToggle}
            className="text-xs text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
            title={isFullscreen ? 'Exit fullscreen' : 'Expand'}
        >
            {isFullscreen ? '\u2716' : '\u26F6'}
        </button>
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

    const rootStyle: React.CSSProperties = {
        display: 'flex',
        flexDirection: 'column',
        maxWidth: 960,
        marginLeft: 'auto',
        marginRight: 'auto',
        width: '100%',
        ...(containerDimensions?.height != null
            ? { height: containerDimensions.height }
            : containerDimensions?.maxHeight != null
              ? { maxHeight: containerDimensions.maxHeight }
              : { minHeight: '100%' }),
    }

    if (!hasContent) {
        const showError = error || isCancelled

        return (
            <div
                style={{
                    ...rootStyle,
                    ...(containerDimensions?.height == null ? { minHeight: 200 } : {}),
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.75rem',
                }}
            >
                <div style={{ animation: showError ? 'none' : 'loading__pulse 4s ease-in-out infinite' }}>
                    <PostHogLogo size={40} />
                </div>
                {isCancelled && (
                    <span style={{ color: 'var(--color-text-secondary, #ca8a04)', fontSize: '0.8125rem' }}>
                        Tool call was cancelled
                    </span>
                )}
                {error && !isCancelled && (
                    <span style={{ color: 'var(--color-text-danger, #dc2626)', fontSize: '0.8125rem' }}>
                        {error.message}
                    </span>
                )}
            </div>
        )
    }

    return (
        <div style={rootStyle}>
            <div style={{ overflow: 'auto' }}>{children(toolResult)}</div>
            <footer
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0.375rem 0.75rem',
                    borderTop: '1px solid var(--color-border-primary, #e5e7eb)',
                    marginTop: 'auto',
                }}
            >
                <ExpandButton app={app} onDisplayModeChanged={refreshContainerDimensions} />
                <span className="ml-auto">
                    {posthogUrl ? (
                        <Link
                            href={posthogUrl}
                            external
                            onClick={(e) => {
                                e.preventDefault()
                                openLink(posthogUrl)
                            }}
                            className="text-xs"
                        >
                            <PostHogLogo size={16} />
                            <span>View in PostHog</span>
                        </Link>
                    ) : (
                        <PostHogLogo size={16} />
                    )}
                </span>
            </footer>
        </div>
    )
}
