import '../emptyState/MCPToolCallPreview.scss'

import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { BrandMarkName } from '../brandMarks'
import { BrandMark } from '../components/BrandMark'
import { harnessMark } from '../dashboard/harnessRegistry'
import { EXAMPLE_TOOL_CALLS } from '../emptyState/exampleToolCalls'
import type { MCPActivityRecentCallApi } from '../generated/api.schemas'
import { formatDuration } from '../sessions/utils'
import { callClientLabel } from './callClient'

const COPY = {
    title: 'Tool calls',
    example: 'example data',
    yours: 'from your server',
    loading: 'Loading your tool calls',
    none: 'No tool calls in the last 30 days',
}

/** As many rows as the example has, so the panel keeps its size when real calls replace it. */
const MAX_ROWS = EXAMPLE_TOOL_CALLS.length

/** `example` before the server has sent anything, `null` while the user's own calls load. */
export type SetupCallsPanelCalls = 'example' | readonly MCPActivityRecentCallApi[] | null

export interface SetupCallsPanelStatus {
    kind: 'listening' | 'live'
    text: string
}

function callTime(call: MCPActivityRecentCallApi): string {
    if (call.is_error) {
        return 'err'
    }
    return call.duration_ms === null ? '' : formatDuration(Math.round(call.duration_ms))
}

function Row({
    mark,
    tool,
    intent,
    time,
    error,
}: {
    mark: BrandMarkName
    tool: string
    intent?: string | null
    time: string
    error?: boolean
}): JSX.Element {
    return (
        <div className={cn('MCPPreview__row', error && 'MCPPreview__row--error')}>
            <span className="MCPPreview__logo">
                <BrandMark name={mark} className="size-3.5" />
            </span>
            <span className="MCPPreview__tool">{tool}</span>
            {intent ? <span className="min-w-0 flex-1 truncate text-xs text-secondary">{intent}</span> : null}
            <span className="MCPPreview__time">{time}</span>
        </div>
    )
}

export function SetupCallsPanel({
    calls,
    status,
}: {
    calls: SetupCallsPanelCalls
    status?: SetupCallsPanelStatus
}): JSX.Element {
    return (
        <div className="MCPPreview">
            <div className="MCPPreview__head">
                <span className="MCPPreview__title">{COPY.title}</span>
                {calls === 'example' ? (
                    <LemonTag size="small">{COPY.example}</LemonTag>
                ) : (
                    <LemonTag size="small" type="success">
                        {COPY.yours}
                    </LemonTag>
                )}
            </div>
            {status ? (
                <div className="MCPPreview__listening pt-2.5">
                    {status.kind === 'listening' ? (
                        <Spinner className="text-sm" />
                    ) : (
                        <span
                            className="size-2 shrink-0 rounded-full bg-success animate-pulse motion-reduce:animate-none"
                            aria-hidden="true"
                        />
                    )}
                    {status.text}
                </div>
            ) : null}
            <div className="MCPPreview__rows">
                {calls === 'example' ? (
                    EXAMPLE_TOOL_CALLS.map((call) => (
                        <Row key={call.tool} mark={call.mark} tool={call.tool} time={call.time} error={call.error} />
                    ))
                ) : calls === null ? (
                    <div className="MCPPreview__listening py-1.5">
                        <Spinner className="text-sm" />
                        {COPY.loading}
                    </div>
                ) : calls.length === 0 ? (
                    <div className="MCPPreview__listening py-1.5">{COPY.none}</div>
                ) : (
                    calls
                        .slice(0, MAX_ROWS)
                        .map((call) => (
                            <Row
                                key={`${call.timestamp}-${call.tool}`}
                                mark={harnessMark(callClientLabel(call))}
                                tool={call.tool}
                                intent={call.intent}
                                time={callTime(call)}
                                error={call.is_error}
                            />
                        ))
                )}
            </div>
        </div>
    )
}
