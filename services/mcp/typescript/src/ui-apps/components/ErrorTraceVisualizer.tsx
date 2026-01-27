import type { ReactElement } from 'react'
import type { ErrorTraceVisualizerProps, StackFrame, ErrorTrace, ExceptionValue } from './types'
import { formatNumber } from './utils'

function formatTimeAgo(dateStr: string | undefined): string {
    if (!dateStr) return '-'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function FrameDisplay({ frame, isExpanded }: { frame: StackFrame; isExpanded?: boolean }): ReactElement {
    const filename = frame.filename || frame.abs_path || 'unknown'
    const shortFilename = filename.split('/').pop() || filename
    const functionName = frame.function || '<anonymous>'
    const isInApp = frame.in_app !== false

    return (
        <div
            style={{
                padding: '0.5rem 0.75rem',
                backgroundColor: isInApp
                    ? 'var(--color-background-primary, #fff)'
                    : 'var(--color-background-secondary, #f9fafb)',
                borderLeft: isInApp
                    ? '3px solid var(--posthog-chart-1, #1d4ed8)'
                    : '3px solid var(--color-border-secondary, #d1d5db)',
                marginBottom: '1px',
            }}
        >
            {/* Function and location */}
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem', flexWrap: 'wrap' }}>
                <code
                    style={{
                        fontFamily: 'var(--font-mono, monospace)',
                        fontSize: '0.8125rem',
                        fontWeight: 600,
                        color: isInApp
                            ? 'var(--color-text-primary, #101828)'
                            : 'var(--color-text-secondary, #6b7280)',
                    }}
                >
                    {functionName}
                </code>
                <span
                    style={{
                        fontSize: '0.75rem',
                        color: 'var(--color-text-secondary, #6b7280)',
                    }}
                >
                    in{' '}
                    <span title={filename} style={{ textDecoration: 'underline', textDecorationStyle: 'dotted' }}>
                        {shortFilename}
                    </span>
                    {frame.lineno && (
                        <>
                            :{frame.lineno}
                            {frame.colno && `:${frame.colno}`}
                        </>
                    )}
                </span>
                {!isInApp && (
                    <span
                        style={{
                            fontSize: '0.625rem',
                            padding: '0.125rem 0.375rem',
                            backgroundColor: 'var(--color-background-tertiary, #f2f4f7)',
                            color: 'var(--color-text-secondary, #6b7280)',
                            borderRadius: 'var(--border-radius-sm, 0.25rem)',
                            textTransform: 'uppercase',
                        }}
                    >
                        library
                    </span>
                )}
            </div>

            {/* Context lines */}
            {isExpanded && frame.context_line && (
                <div
                    style={{
                        marginTop: '0.5rem',
                        fontFamily: 'var(--font-mono, monospace)',
                        fontSize: '0.75rem',
                        backgroundColor: 'var(--color-background-tertiary, #1f2937)',
                        borderRadius: 'var(--border-radius-sm, 0.25rem)',
                        overflow: 'hidden',
                    }}
                >
                    {/* Pre-context */}
                    {frame.pre_context?.map((line, i) => (
                        <div
                            key={`pre-${i}`}
                            style={{
                                padding: '0 0.5rem',
                                color: 'var(--color-text-tertiary, #9ca3af)',
                                whiteSpace: 'pre',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                            }}
                        >
                            <span style={{ display: 'inline-block', width: '3rem', textAlign: 'right', marginRight: '0.5rem', opacity: 0.5 }}>
                                {(frame.lineno || 0) - (frame.pre_context?.length || 0) + i}
                            </span>
                            {line}
                        </div>
                    ))}

                    {/* Current line (highlighted) */}
                    <div
                        style={{
                            padding: '0.25rem 0.5rem',
                            backgroundColor: 'var(--color-background-danger, rgba(220, 38, 38, 0.1))',
                            color: 'var(--color-text-primary, #f9fafb)',
                            whiteSpace: 'pre',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            borderLeft: '2px solid var(--color-text-danger, #dc2626)',
                        }}
                    >
                        <span style={{ display: 'inline-block', width: '3rem', textAlign: 'right', marginRight: '0.5rem', fontWeight: 600 }}>
                            {frame.lineno}
                        </span>
                        {frame.context_line}
                    </div>

                    {/* Post-context */}
                    {frame.post_context?.map((line, i) => (
                        <div
                            key={`post-${i}`}
                            style={{
                                padding: '0 0.5rem',
                                color: 'var(--color-text-tertiary, #9ca3af)',
                                whiteSpace: 'pre',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                            }}
                        >
                            <span style={{ display: 'inline-block', width: '3rem', textAlign: 'right', marginRight: '0.5rem', opacity: 0.5 }}>
                                {(frame.lineno || 0) + 1 + i}
                            </span>
                            {line}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

function ExceptionDisplay({ exception }: { exception: ExceptionValue }): ReactElement {
    const frames = exception.stacktrace?.frames || []
    // Reverse frames so most recent is at top (Sentry format has oldest first)
    const reversedFrames = [...frames].reverse()

    return (
        <div style={{ marginBottom: '1.5rem' }}>
            {/* Exception header */}
            <div
                style={{
                    padding: '0.75rem',
                    backgroundColor: 'var(--color-background-danger, #fef2f2)',
                    border: '1px solid var(--color-border-danger, #fecaca)',
                    borderRadius: 'var(--border-radius-md, 0.375rem)',
                    marginBottom: '0.75rem',
                }}
            >
                <div
                    style={{
                        fontFamily: 'var(--font-mono, monospace)',
                        fontSize: '0.875rem',
                        fontWeight: 600,
                        color: 'var(--color-text-danger, #dc2626)',
                    }}
                >
                    {exception.type || 'Error'}
                </div>
                {exception.value && (
                    <div
                        style={{
                            marginTop: '0.25rem',
                            fontSize: '0.8125rem',
                            color: 'var(--color-text-primary, #101828)',
                            wordBreak: 'break-word',
                        }}
                    >
                        {exception.value}
                    </div>
                )}
            </div>

            {/* Stack frames */}
            {reversedFrames.length > 0 && (
                <div
                    style={{
                        border: '1px solid var(--color-border-primary, #e5e7eb)',
                        borderRadius: 'var(--border-radius-md, 0.375rem)',
                        overflow: 'hidden',
                    }}
                >
                    {reversedFrames.map((frame, i) => (
                        <FrameDisplay key={i} frame={frame} isExpanded={frame.in_app !== false} />
                    ))}
                </div>
            )}
        </div>
    )
}

function normalizeTrace(trace: ErrorTrace): ExceptionValue[] {
    // Handle nested exception format
    if (trace.exception?.values) {
        return trace.exception.values
    }

    // Handle flat format
    if (trace.exception_type || trace.frames) {
        return [
            {
                type: trace.exception_type,
                value: trace.exception_message,
                stacktrace: trace.frames ? { frames: trace.frames } : undefined,
            },
        ]
    }

    return []
}

export function ErrorTraceVisualizer({ issue, traces }: ErrorTraceVisualizerProps): ReactElement {
    if (!traces || traces.length === 0) {
        return (
            <div
                style={{
                    padding: '2rem',
                    textAlign: 'center',
                    color: 'var(--color-text-secondary, #6b7280)',
                }}
            >
                No stack trace available
            </div>
        )
    }

    // Get all exceptions from all traces
    const allExceptions = traces.flatMap(normalizeTrace)

    return (
        <div>
            {/* Issue summary */}
            <div
                style={{
                    display: 'flex',
                    gap: '1.5rem',
                    marginBottom: '1rem',
                    padding: '0.75rem',
                    backgroundColor: 'var(--color-background-secondary, #f9fafb)',
                    borderRadius: 'var(--border-radius-md, 0.375rem)',
                    flexWrap: 'wrap',
                }}
            >
                <div>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--color-text-secondary, #6b7280)', textTransform: 'uppercase' }}>
                        Occurrences
                    </div>
                    <div style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--color-text-primary, #101828)' }}>
                        {formatNumber(issue.occurrences || 0)}
                    </div>
                </div>
                <div>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--color-text-secondary, #6b7280)', textTransform: 'uppercase' }}>
                        Users affected
                    </div>
                    <div style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--color-text-primary, #101828)' }}>
                        {formatNumber(issue.users || 0)}
                    </div>
                </div>
                <div>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--color-text-secondary, #6b7280)', textTransform: 'uppercase' }}>
                        First seen
                    </div>
                    <div style={{ fontSize: '0.875rem', color: 'var(--color-text-primary, #101828)' }}>
                        {formatTimeAgo(issue.first_seen)}
                    </div>
                </div>
                <div>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--color-text-secondary, #6b7280)', textTransform: 'uppercase' }}>
                        Last seen
                    </div>
                    <div style={{ fontSize: '0.875rem', color: 'var(--color-text-primary, #101828)' }}>
                        {formatTimeAgo(issue.last_seen)}
                    </div>
                </div>
            </div>

            {/* Exception(s) */}
            {allExceptions.length > 0 ? (
                allExceptions.map((exception, i) => <ExceptionDisplay key={i} exception={exception} />)
            ) : (
                <div
                    style={{
                        padding: '1rem',
                        backgroundColor: 'var(--color-background-secondary, #f9fafb)',
                        borderRadius: 'var(--border-radius-md, 0.375rem)',
                        color: 'var(--color-text-secondary, #6b7280)',
                        fontFamily: 'var(--font-mono, monospace)',
                        fontSize: '0.8125rem',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                    }}
                >
                    {JSON.stringify(traces, null, 2)}
                </div>
            )}
        </div>
    )
}
