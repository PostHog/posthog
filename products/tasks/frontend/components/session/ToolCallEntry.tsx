import { useState } from 'react'

import { IconChevronRight, IconTerminal } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

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

export function ToolCallEntry({ toolName, status, args, result, timestamp }: ToolCallEntryProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
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
                    {args && (
                        <div className="mb-2">
                            <div className="text-xs font-medium text-muted mb-1">Arguments</div>
                            <pre className="text-xs overflow-x-auto whitespace-pre-wrap break-words">
                                {JSON.stringify(args, null, 2)}
                            </pre>
                        </div>
                    )}
                    {result !== undefined && (
                        <div>
                            <div className="text-xs font-medium text-muted mb-1">Result</div>
                            <pre className="text-xs overflow-x-auto whitespace-pre-wrap break-words">
                                {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
                            </pre>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
