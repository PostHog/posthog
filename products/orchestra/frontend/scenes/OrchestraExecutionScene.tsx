import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    orchestraExecutionLogic,
    OrchestraExecutionLogicProps,
    OrchestraEvent,
} from '../logics/orchestraExecutionLogic'

type SpanKind = 'step' | 'timer'
type SpanStatus = 'completed' | 'failed' | 'running'

interface Span {
    label: string
    kind: SpanKind
    status: SpanStatus
    startMs: number
    endMs: number | null
}

function computeSpans(
    events: OrchestraEvent[],
    executionStartedAt: string,
    executionFinishedAt: string | null
): { spans: Span[]; totalMs: number } {
    const startEpoch = new Date(executionStartedAt).getTime()
    const endEpoch = executionFinishedAt ? new Date(executionFinishedAt).getTime() : Date.now()
    const pendingSteps = new Map<number, { label: string; startMs: number }>()
    const pendingTimers = new Map<number, { label: string; startMs: number }>()
    const completed: Span[] = []

    for (const e of events) {
        const t = new Date(e.timestamp).getTime() - startEpoch
        const attrs = e.attributes as Record<string, any>
        if (e.event_type === 'STEP_SCHEDULED') {
            pendingSteps.set(attrs.step_id, { label: String(attrs.step_type ?? 'step'), startMs: t })
        } else if (e.event_type === 'STEP_COMPLETED' || e.event_type === 'STEP_FAILED') {
            const start = pendingSteps.get(attrs.step_id)
            if (start) {
                completed.push({
                    label: start.label,
                    kind: 'step',
                    status: e.event_type === 'STEP_COMPLETED' ? 'completed' : 'failed',
                    startMs: start.startMs,
                    endMs: t,
                })
                pendingSteps.delete(attrs.step_id)
            }
        } else if (e.event_type === 'TIMER_SCHEDULED') {
            const seconds = Number(attrs.seconds ?? 0)
            pendingTimers.set(attrs.timer_id, {
                label: `sleep ${seconds}s`,
                startMs: t,
            })
        } else if (e.event_type === 'TIMER_FIRED') {
            const start = pendingTimers.get(attrs.timer_id)
            if (start) {
                completed.push({
                    label: start.label,
                    kind: 'timer',
                    status: 'completed',
                    startMs: start.startMs,
                    endMs: t,
                })
                pendingTimers.delete(attrs.timer_id)
            }
        }
    }

    const stillRunning: Span[] = []
    for (const v of pendingSteps.values()) {
        stillRunning.push({ label: v.label, kind: 'step', status: 'running', startMs: v.startMs, endMs: null })
    }
    for (const v of pendingTimers.values()) {
        stillRunning.push({ label: v.label, kind: 'timer', status: 'running', startMs: v.startMs, endMs: null })
    }

    const spans = [...completed, ...stillRunning].sort((a, b) => a.startMs - b.startMs)
    const totalMs = Math.max(1, endEpoch - startEpoch)
    return { spans, totalMs }
}

function formatMs(ms: number): string {
    if (ms < 1000) {
        return `${Math.max(0, Math.round(ms))}ms`
    }
    return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}s`
}

function spanBgStyle(span: Span): { className: string; style?: React.CSSProperties } {
    if (span.status === 'failed') {
        return { className: 'bg-danger' }
    }
    if (span.status === 'running') {
        return { className: 'bg-primary animate-pulse' }
    }
    if (span.kind === 'timer') {
        // Yellow hatched bar reads as "waiting, not working" in both light and dark mode.
        return {
            className: '',
            style: {
                backgroundColor: 'var(--warning)',
                backgroundImage: 'repeating-linear-gradient(45deg, rgba(0, 0, 0, 0.18) 0 6px, transparent 6px 12px)',
            },
        }
    }
    return { className: 'bg-success' }
}

function TraceTimeline({
    events,
    executionStartedAt,
    executionFinishedAt,
}: {
    events: OrchestraEvent[]
    executionStartedAt: string
    executionFinishedAt: string | null
}): JSX.Element {
    const { spans, totalMs } = computeSpans(events, executionStartedAt, executionFinishedAt)

    if (spans.length === 0) {
        return <div className="text-muted text-sm">No steps yet.</div>
    }

    return (
        <div className="border rounded bg-bg-light p-3">
            <div className="flex items-center text-xs text-muted mb-2 pl-[200px]">
                <span>0ms</span>
                <span className="ml-auto">{formatMs(totalMs)}</span>
            </div>
            <div className="flex flex-col gap-1">
                {spans.map((span, idx) => {
                    const startPct = (span.startMs / totalMs) * 100
                    const widthRawMs = (span.endMs ?? totalMs) - span.startMs
                    const widthPct = Math.max(0.5, (widthRawMs / totalMs) * 100)
                    const durationLabel =
                        span.endMs == null ? `running (${formatMs(widthRawMs)})` : formatMs(span.endMs - span.startMs)
                    return (
                        <div key={idx} className="flex items-center gap-3 h-6">
                            <div
                                className="text-sm truncate text-right pr-2"
                                style={{ width: 200, flex: '0 0 200px' }}
                                title={span.label}
                            >
                                <code>{span.label}</code>
                            </div>
                            <div className="relative flex-1 h-full bg-bg-3000 rounded-sm overflow-hidden">
                                {(() => {
                                    const { className, style } = spanBgStyle(span)
                                    return (
                                        <Tooltip title={`${span.label} — ${durationLabel}`}>
                                            <div
                                                className={`absolute top-0 bottom-0 rounded-sm ${className}`}
                                                style={{
                                                    left: `${startPct}%`,
                                                    width: `${widthPct}%`,
                                                    ...style,
                                                }}
                                            />
                                        </Tooltip>
                                    )
                                })()}
                            </div>
                            <div className="text-xs text-muted tabular-nums w-20 text-right">{durationLabel}</div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: OrchestraExecutionScene,
    logic: orchestraExecutionLogic,
    paramsToProps: ({ params: { id } }): OrchestraExecutionLogicProps => ({
        executionId: id,
    }),
}

function OrchestraExecutionScene(): JSX.Element {
    const { execution, executionLoading } = useValues(orchestraExecutionLogic)

    if (executionLoading || !execution) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading..." resourceType={{ type: 'orchestra' }} />
            </SceneContent>
        )
    }

    const statusType =
        execution.status === 'COMPLETED' ? 'success' : execution.status === 'FAILED' ? 'danger' : 'default'

    const eventColumns: LemonTableColumns<OrchestraEvent> = [
        {
            title: 'Event ID',
            dataIndex: 'event_id',
            width: 80,
        },
        {
            title: 'Type',
            dataIndex: 'event_type',
            render: (_, record) => <LemonTag>{record.event_type}</LemonTag>,
        },
        {
            title: 'Time',
            dataIndex: 'timestamp',
            render: (_, record) => dayjs(record.timestamp).format('HH:mm:ss.SSS'),
        },
        {
            title: 'Attributes',
            dataIndex: 'attributes',
            render: (_, record) => (
                <CodeSnippet language={Language.JSON} wrap compact>
                    {JSON.stringify(record.attributes, null, 2)}
                </CodeSnippet>
            ),
        },
    ]

    const durationMs = execution.finished_at
        ? dayjs(execution.finished_at).diff(dayjs(execution.started_at), 'millisecond')
        : null
    const durationLabel =
        durationMs == null ? null : durationMs < 1000 ? `${durationMs}ms` : `${(durationMs / 1000).toFixed(2)}s`

    return (
        <SceneContent>
            <SceneTitleSection
                name={`Execution: ${execution.execution_id}`}
                description={execution.execution_type}
                resourceType={{ type: 'orchestra' }}
            />
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <LemonTag type={statusType}>{execution.status}</LemonTag>
                <span>
                    <span className="text-muted mr-1">Started</span>
                    <TZLabel time={execution.started_at} timestampStyle="absolute" />
                </span>
                <span>
                    <span className="text-muted mr-1">Finished</span>
                    {execution.finished_at ? (
                        <TZLabel time={execution.finished_at} timestampStyle="absolute" />
                    ) : (
                        <span className="italic">running…</span>
                    )}
                </span>
                {durationLabel && (
                    <span>
                        <span className="text-muted mr-1">Duration</span>
                        <code>{durationLabel}</code>
                    </span>
                )}
            </div>
            {execution.input != null && (
                <div>
                    <h3 className="mb-2">Input</h3>
                    <CodeSnippet language={Language.JSON} wrap compact>
                        {JSON.stringify(execution.input, null, 2)}
                    </CodeSnippet>
                </div>
            )}
            {execution.result != null && (
                <div>
                    <h3 className="mb-2">Result</h3>
                    <CodeSnippet language={Language.JSON} wrap compact>
                        {JSON.stringify(execution.result, null, 2)}
                    </CodeSnippet>
                </div>
            )}
            {execution.error != null && (
                <div>
                    <h3 className="mb-2">Error</h3>
                    <CodeSnippet language={Language.JSON} wrap compact>
                        {JSON.stringify(execution.error, null, 2)}
                    </CodeSnippet>
                </div>
            )}

            <h3 className="mb-2">Trace</h3>
            <TraceTimeline
                events={execution.events || []}
                executionStartedAt={execution.started_at}
                executionFinishedAt={execution.finished_at}
            />

            <h3 className="mb-2 mt-6">Event timeline</h3>
            <LemonTable
                columns={eventColumns}
                dataSource={execution.events || []}
                emptyState="No events"
                size="small"
            />
        </SceneContent>
    )
}
