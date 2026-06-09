import { JSX, ReactNode } from 'react'

import { Spinner as LemonSpinner } from '@posthog/lemon-ui'

import { ToolCall, ToolCallContent } from '../acp-types'
import { getFileName } from '../lib/path'
import { ICONS, Icon } from './icons'

export function ToolTitle({ children, className }: { children: ReactNode; className?: string }): JSX.Element {
    return <span className={`text-[13px] text-muted${className ? ` ${className}` : ''}`}>{children}</span>
}

export function StatusIndicators({
    isFailed,
    wasCancelled,
}: {
    isFailed?: boolean
    wasCancelled?: boolean
}): JSX.Element {
    return (
        <>
            {isFailed && <span className="text-[13px] text-muted">(Failed)</span>}
            {wasCancelled && <span className="text-[13px] text-muted">(Cancelled)</span>}
        </>
    )
}

export function useToolCallStatus(
    status: ToolCall['status'],
    turnCancelled?: boolean,
    turnComplete?: boolean
): {
    isIncomplete: boolean
    isLoading: boolean
    isFailed: boolean
    wasCancelled: boolean
    isComplete: boolean
} {
    const isIncomplete = status === 'pending' || status === 'in_progress'
    const isLoading = isIncomplete && !turnCancelled && !turnComplete
    const isFailed = status === 'failed'
    const wasCancelled = isIncomplete && !!turnCancelled
    const isComplete = status === 'completed'

    return { isIncomplete, isLoading, isFailed, wasCancelled, isComplete }
}

function extractText(item: ToolCallContent | undefined): string | undefined {
    if (item?.type === 'content' && item.content.type === 'text') {
        return item.content.text
    }
    return undefined
}

export function getContentText(content: ToolCall['content']): string | undefined {
    if (!content?.length) {
        return undefined
    }
    for (const item of content) {
        const text = extractText(item)
        if (text !== undefined) {
            return text
        }
    }
    return undefined
}

export interface ImageContentData {
    base64: string
    mimeType: string
}

export function getContentImage(content: ToolCall['content']): ImageContentData | null {
    if (!content?.length) {
        return null
    }
    for (const item of content) {
        if (item.type === 'content' && item.content.type === 'image') {
            const { data, mimeType } = item.content
            if (typeof data === 'string' && typeof mimeType === 'string') {
                return { base64: data, mimeType }
            }
        }
    }
    return null
}

export function getReadToolContent(content: ToolCall['content']): string | undefined {
    const raw = getContentText(content)
    if (!raw) {
        return undefined
    }

    let text = raw
    text = text.replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, '')
    text = text.replace(/^```\w*\n?/, '').replace(/\n?```\s*$/, '')
    text = text
        .split('\n')
        .map((line) => line.replace(/^\s*\d+→/, ''))
        .join('\n')
    text = text.trim()

    return text || undefined
}

export function getLineCount(content: ToolCall['content']): number | null {
    const text = getContentText(content)
    return text ? text.split('\n').length : null
}

const INPUT_PREVIEW_MAX_LENGTH = 60

export function compactInput(rawInput: unknown): string | undefined {
    if (!rawInput || typeof rawInput !== 'object') {
        return undefined
    }
    try {
        const json = JSON.stringify(rawInput)
        if (json === '{}') {
            return undefined
        }
        if (json.length <= INPUT_PREVIEW_MAX_LENGTH) {
            return json
        }
        return `${json.slice(0, INPUT_PREVIEW_MAX_LENGTH)}...`
    } catch {
        return undefined
    }
}

export function formatInput(rawInput: unknown): string | undefined {
    if (!rawInput || typeof rawInput !== 'object') {
        return undefined
    }
    try {
        const json = JSON.stringify(rawInput, null, 2)
        if (json === '{}') {
            return undefined
        }
        return json
    } catch {
        return undefined
    }
}

export function stripCodeFences(text: string): string {
    return text.replace(/^```\w*\n?/, '').replace(/\n?```\s*$/, '')
}

export function truncateText(text: string, maxLength: number, ellipsis = '…'): string {
    if (typeof text !== 'string') {
        return String(text)
    }
    if (text.length <= maxLength) {
        return text
    }
    return `${text.slice(0, maxLength)}${ellipsis}`
}

export function getFilename(path: string): string {
    if (typeof path !== 'string') {
        return String(path)
    }
    return getFileName(path)
}

export type DiffContent = Extract<ToolCallContent, { type: 'diff' }>

export function findDiffContent(content: ToolCallContent[] | null | undefined): DiffContent | undefined {
    return content?.find((c): c is DiffContent => c.type === 'diff')
}

export interface ResourceLinkData {
    uri?: string
    name?: string
    description?: string
}

export function findResourceLink(content: ToolCall['content']): ResourceLinkData | undefined {
    if (!content?.length) {
        return undefined
    }
    const item = content[0]
    if (item.type === 'content' && item.content.type === 'resource_link') {
        return item.content as { type: 'resource_link' } & ResourceLinkData
    }
    return undefined
}

export interface ToolViewProps {
    toolCall: ToolCall
    turnCancelled?: boolean
    turnComplete?: boolean
    expanded?: boolean
}

const ICON_SIZE = 12
const ICON_CLASS = 'text-default'

function Spinner({ className = ICON_CLASS }: { className?: string }): JSX.Element {
    return <LemonSpinner className={`text-[12px] ${className}`} size="small" textColored />
}

export function LoadingIcon({
    icon: IconComponent,
    isLoading,
    className = ICON_CLASS,
}: {
    icon: Icon
    isLoading: boolean
    className?: string
}): JSX.Element {
    if (isLoading) {
        return <Spinner className={className} />
    }
    return <IconComponent className={className} style={{ fontSize: ICON_SIZE }} />
}

export function ExpandableIcon({
    icon: IconComponent,
    isLoading,
    isExpandable,
    isExpanded,
}: {
    icon: Icon
    isLoading: boolean
    isExpandable: boolean
    isExpanded: boolean
}): JSX.Element {
    const Minus = ICONS.Minus
    const Plus = ICONS.Plus
    if (isLoading) {
        return <Spinner />
    }
    if (!isExpandable) {
        return <IconComponent className={ICON_CLASS} style={{ fontSize: ICON_SIZE }} />
    }
    return (
        <>
            <IconComponent className={`${ICON_CLASS} group-hover:hidden`} style={{ fontSize: ICON_SIZE }} />
            {isExpanded ? (
                <Minus className={`hidden ${ICON_CLASS} group-hover:block`} style={{ fontSize: ICON_SIZE }} />
            ) : (
                <Plus className={`hidden ${ICON_CLASS} group-hover:block`} style={{ fontSize: ICON_SIZE }} />
            )}
        </>
    )
}

export function ContentPre({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="max-h-64 overflow-auto px-3 py-2">
            <pre className="m-0 whitespace-pre-wrap break-all font-mono text-[13px] text-muted">{children}</pre>
        </div>
    )
}

export function ExpandedContentBox({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="mt-2 ml-5 max-w-4xl overflow-hidden rounded-lg border border-border">
            <ContentPre>{children}</ContentPre>
        </div>
    )
}
