import { useState } from 'react'

import { IconChevronRight, IconTerminal } from '@posthog/icons'
import { LemonSwitch, LemonTag, Spinner } from '@posthog/lemon-ui'

import { ToolStatus } from '../../lib/parse-logs'

interface ToolCallEntryProps {
    toolName: string
    status: ToolStatus
    args?: Record<string, unknown>
    result?: unknown
    timestamp?: string
}

const STATUS_CONFIG: Record<ToolStatus, { label: string; type: 'default' | 'primary' | 'success' | 'danger' }> = {
    pending: { label: 'Pending', type: 'default' },
    running: { label: 'Running', type: 'primary' },
    completed: { label: 'Done', type: 'success' },
    error: { label: 'Failed', type: 'danger' },
}

function isTextPart(item: unknown): item is { type: 'text'; text: string } {
    return (
        typeof item === 'object' &&
        item !== null &&
        (item as Record<string, unknown>).type === 'text' &&
        typeof (item as Record<string, unknown>).text === 'string'
    )
}

// Returns the parsed value only when the string is a JSON object/array, otherwise undefined.
function tryParseJson(text: string): unknown {
    const trimmed = text.trim()
    const first = trimmed[0]
    if (first !== '{' && first !== '[') {
        return undefined
    }
    try {
        return JSON.parse(trimmed)
    } catch {
        return undefined
    }
}

// Recursively expand any string that is itself JSON, so double-encoded payloads render as real structure.
function expandEmbeddedJson(value: unknown): unknown {
    if (typeof value === 'string') {
        const parsed = tryParseJson(value)
        return parsed !== undefined ? expandEmbeddedJson(parsed) : value
    }
    if (Array.isArray(value)) {
        return value.map(expandEmbeddedJson)
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value as Record<string, unknown>).map(([key, val]) => [key, expandEmbeddedJson(val)])
        )
    }
    return value
}

// MCP tool results usually arrive as [{ type: 'text', text: '...' }]; pull the text out so newlines render.
function extractTextParts(value: unknown): string | null {
    const items = Array.isArray(value) ? value : [value]
    const texts: string[] = []
    for (const item of items) {
        if (!isTextPart(item)) {
            return null
        }
        texts.push(item.text)
    }
    return texts.length ? texts.join('\n\n') : null
}

function formatValue(value: unknown, pretty: boolean): string {
    if (!pretty) {
        return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
    }
    const text = extractTextParts(value)
    const candidate = text ?? (typeof value === 'string' ? value : null)
    if (candidate !== null) {
        const parsed = tryParseJson(candidate)
        return parsed !== undefined ? JSON.stringify(expandEmbeddedJson(parsed), null, 2) : candidate
    }
    return JSON.stringify(expandEmbeddedJson(value), null, 2)
}

export function ToolCallEntry({ toolName, status, args, result, timestamp }: ToolCallEntryProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [pretty, setPretty] = useState(true)
    const config = STATUS_CONFIG[status]
    const hasContent = args || result !== undefined
    const isLoading = status === 'pending' || status === 'running'

    const HeaderContent = (
        <>
            {timestamp && <span className="text-xs text-muted">{new Date(timestamp).toLocaleTimeString()}</span>}
            {hasContent && (
                <IconChevronRight
                    className={`text-muted transition-transform ${isOpen ? 'rotate-90' : ''}`}
                    fontSize="12"
                />
            )}
            {isLoading ? <Spinner className="text-muted" /> : <IconTerminal className="text-muted" fontSize="14" />}
            <code className="text-xs text-secondary">{toolName}</code>
            <LemonTag type={config.type} size="small">
                {config.label}
            </LemonTag>
        </>
    )

    return (
        <div className="py-2">
            {hasContent ? (
                <button
                    type="button"
                    onClick={() => setIsOpen(!isOpen)}
                    className="flex items-center gap-2 w-full text-left rounded hover:bg-bg-light cursor-pointer"
                >
                    {HeaderContent}
                </button>
            ) : (
                <div className="flex items-center gap-2 w-full text-left rounded">{HeaderContent}</div>
            )}

            {isOpen && hasContent && (
                <div className="ml-5 mt-1 rounded bg-bg-light p-2 overflow-hidden">
                    <div className="flex justify-end mb-1">
                        <LemonSwitch
                            label="Pretty print"
                            checked={pretty}
                            onChange={setPretty}
                            size="xsmall"
                            bordered
                        />
                    </div>
                    {args && (
                        <div className="mb-2">
                            <div className="text-xs font-medium text-muted mb-1">Arguments</div>
                            <pre className="text-xs overflow-x-auto whitespace-pre-wrap break-words">
                                {formatValue(args, pretty)}
                            </pre>
                        </div>
                    )}
                    {result !== undefined && (
                        <div>
                            <div className="text-xs font-medium text-muted mb-1">Result</div>
                            <pre className="text-xs overflow-x-auto whitespace-pre-wrap break-words">
                                {formatValue(result, pretty)}
                            </pre>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
