import type { ReactElement } from 'react'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger, Badge, Card, Stack } from '@posthog/mosaic'

export interface StackFrame {
    raw_id?: string
    mangled_name?: string
    resolved_name?: string | null
    source?: string | null
    line?: number | null
    column?: number | null
    in_app?: boolean
    lang?: string
    resolved?: boolean
    context?: {
        before?: Array<{ number: number; line: string }>
        line?: { number: number; line: string }
        after?: Array<{ number: number; line: string }>
    } | null
}

export interface ExceptionData {
    type: string
    value: string
    module?: string
    mechanism?: { handled?: boolean; type?: string }
    stacktrace?: {
        type?: string
        frames?: StackFrame[]
    }
}

export interface StackTraceViewProps {
    exceptions: ExceptionData[]
}

function formatFrameLocation(frame: StackFrame): string {
    const parts: string[] = []
    if (frame.source) {
        parts.push(frame.source)
    }
    if (frame.line != null) {
        parts.push(`:${frame.line}`)
        if (frame.column != null) {
            parts.push(`:${frame.column}`)
        }
    }
    return parts.join('')
}

function FrameContextLines({ context }: { context: NonNullable<StackFrame['context']> }): ReactElement {
    const allLines = [
        ...(context.before ?? []).map((l) => ({ ...l, type: 'context' as const })),
        ...(context.line ? [{ ...context.line, type: 'error' as const }] : []),
        ...(context.after ?? []).map((l) => ({ ...l, type: 'context' as const })),
    ]

    return (
        <pre className="text-xs overflow-x-auto bg-bg-secondary rounded p-2 font-mono leading-relaxed">
            {allLines.map((l, i) => (
                <div key={i} className={l.type === 'error' ? 'bg-danger/10 -mx-2 px-2' : ''}>
                    <span className="inline-block w-10 text-right text-text-secondary select-none pr-3 tabular-nums">
                        {l.number}
                    </span>
                    <span className={l.type === 'error' ? 'text-text-danger font-medium' : 'text-text-primary'}>
                        {l.line}
                    </span>
                </div>
            ))}
        </pre>
    )
}

function FrameRow({ frame, index }: { frame: StackFrame; index: number }): ReactElement {
    const funcName = frame.resolved_name || frame.mangled_name || '<anonymous>'
    const location = formatFrameLocation(frame)
    const hasContext =
        frame.context && (frame.context.before?.length || frame.context.line || frame.context.after?.length)

    if (!hasContext) {
        return (
            <div className="flex items-start gap-2 py-1.5 px-2 text-xs font-mono">
                <span className={frame.in_app ? 'text-text-primary font-medium' : 'text-text-secondary'}>
                    {funcName}
                </span>
                {location && <span className="text-text-secondary truncate ml-auto shrink-0">{location}</span>}
                {frame.in_app === false && (
                    <Badge variant="neutral" size="sm" className="ml-1 shrink-0">
                        vendor
                    </Badge>
                )}
            </div>
        )
    }

    return (
        <AccordionItem value={`frame-${index}`}>
            <AccordionTrigger className="px-2">
                <div className="flex items-center gap-2 min-w-0">
                    <span
                        className={
                            frame.in_app
                                ? 'text-text-primary font-medium font-mono text-xs'
                                : 'text-text-secondary font-mono text-xs'
                        }
                    >
                        {funcName}
                    </span>
                    {location && (
                        <span className="text-text-secondary text-xs truncate ml-auto shrink-0">{location}</span>
                    )}
                    {frame.in_app === false && (
                        <Badge variant="neutral" size="sm" className="shrink-0">
                            vendor
                        </Badge>
                    )}
                </div>
            </AccordionTrigger>
            <AccordionContent className="pl-6 pr-2">
                <FrameContextLines context={frame.context!} />
            </AccordionContent>
        </AccordionItem>
    )
}

function ExceptionSection({ exception, index }: { exception: ExceptionData; index: number }): ReactElement {
    const frames = exception.stacktrace?.frames ?? []
    // Reverse frames so most recent call is at the top (Python/JS convention)
    const displayFrames = [...frames].reverse()
    const inAppCount = frames.filter((f) => f.in_app).length

    return (
        <Card padding="md">
            <Stack gap="sm">
                <div className="flex items-center gap-2 flex-wrap">
                    {index > 0 && (
                        <span className="text-xs text-text-secondary uppercase tracking-wide">Caused by</span>
                    )}
                    <Badge variant="danger" size="md">
                        {exception.type}
                    </Badge>
                    {exception.mechanism?.handled === false && (
                        <Badge variant="warning" size="sm">
                            Unhandled
                        </Badge>
                    )}
                </div>
                <span className="text-sm text-text-primary">{exception.value}</span>

                {displayFrames.length > 0 && (
                    <div className="mt-1">
                        <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs text-text-secondary">
                                {displayFrames.length} frame{displayFrames.length === 1 ? '' : 's'}
                            </span>
                            {inAppCount > 0 && (
                                <span className="text-xs text-text-secondary">({inAppCount} in-app)</span>
                            )}
                        </div>
                        <div className="rounded border border-border-primary overflow-hidden">
                            <Accordion multiple defaultExpanded={getDefaultExpanded(displayFrames)}>
                                {displayFrames.map((frame, i) => (
                                    <FrameRow key={frame.raw_id ?? i} frame={frame} index={i} />
                                ))}
                            </Accordion>
                        </div>
                    </div>
                )}
            </Stack>
        </Card>
    )
}

/** Auto-expand the first in-app frame that has context */
function getDefaultExpanded(frames: StackFrame[]): string[] {
    const idx = frames.findIndex(
        (f) => f.in_app && f.context && (f.context.before?.length || f.context.line || f.context.after?.length)
    )
    return idx >= 0 ? [`frame-${idx}`] : []
}

export function StackTraceView({ exceptions }: StackTraceViewProps): ReactElement {
    if (exceptions.length === 0) {
        return <div className="text-sm text-text-secondary p-4">No exception data available</div>
    }

    return (
        <Stack gap="md">
            {exceptions.map((exception, i) => (
                <ExceptionSection key={i} exception={exception} index={i} />
            ))}
        </Stack>
    )
}
