import clsx from 'clsx'
import { type ReactNode, useEffect, useRef } from 'react'

import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

/** Bounded text preview; full output opens as plain text without another scroll container in the chat. */
export function ToolOutput({ children }: { children: ReactNode }): JSX.Element {
    const urls = useRef<string[]>([])
    useEffect(
        () => () => {
            urls.current.forEach((url) => URL.revokeObjectURL(url))
        },
        []
    )
    const text = typeof children === 'string' ? children : undefined
    const preview = text?.slice(0, 4000).split('\n').slice(0, 12).join('\n')
    const truncated = text !== undefined && preview !== text
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <pre className="m-0 font-mono text-xs leading-relaxed text-secondary whitespace-pre-wrap break-all">
                {preview ?? children}
                {truncated ? '\n…' : ''}
            </pre>
            {text !== undefined && (
                <div className="flex gap-1">
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        icon={<IconCopy />}
                        tooltip="Copy"
                        data-attr="tool-output-copy"
                        onClick={() => void copyToClipboard(text, 'tool text')}
                    />
                    {truncated && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconExternal />}
                            tooltip="Open full text in a new tab"
                            data-attr="tool-output-open"
                            onClick={() => {
                                const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
                                urls.current.push(url)
                                window.open(url, '_blank', 'noopener,noreferrer')
                            }}
                        />
                    )}
                </div>
            )}
        </div>
    )
}

/** Vertical container stacking a tool card's body sections (input, output) with consistent spacing. */
export function ToolBody({ children }: { children: ReactNode }): JSX.Element {
    return <div className="flex flex-col gap-2 min-w-0">{children}</div>
}

/** A `ToolBody` section; `divided` draws a top border to separate it from the section above it. */
export function ToolBodySection({
    divided = false,
    children,
}: {
    divided?: boolean
    children: ReactNode
}): JSX.Element {
    return <div className={clsx('min-w-0', divided && 'border-t border-border-secondary pt-2')}>{children}</div>
}
