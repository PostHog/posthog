import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { BrandMark } from '../components/BrandMark'
import { harnessMark } from '../dashboard/harnessRegistry'
import type { MCPActivityRecentCallApi } from '../generated/api.schemas'
import { formatDuration } from '../sessions/utils'

const UNIDENTIFIED_CLIENT = 'Unidentified client'

/** One tool call shown in full: who called which tool, why, and how it went. */
export function ToolCallRevealCard({ call }: { call: MCPActivityRecentCallApi }): JSX.Element {
    const client = call.client_name || UNIDENTIFIED_CLIENT
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4" data-attr="mcp-analytics-setup-mode-call">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="inline-flex min-w-0 items-center gap-1.5 font-semibold">
                    <BrandMark name={harnessMark(client)} />
                    <span className="truncate">{client}</span>
                </span>
                <span className="text-secondary">called</span>
                <span className="min-w-0 truncate font-mono font-semibold">{call.tool}</span>
                <LemonTag type={call.is_error ? 'danger' : 'success'}>
                    {call.is_error
                        ? 'Failed'
                        : call.duration_ms !== null
                          ? `OK in ${formatDuration(Math.round(call.duration_ms))}`
                          : 'OK'}
                </LemonTag>
                <span className="ml-auto text-xs text-secondary">
                    <TZLabel time={call.timestamp} />
                </span>
            </div>
            {call.intent ? (
                <div className="flex flex-col gap-0.5">
                    <span className="text-xs font-semibold text-secondary">What the agent was trying to do</span>
                    <span>{call.intent}</span>
                </div>
            ) : null}
            {call.is_error && call.error_message ? (
                <div className="flex flex-col gap-0.5">
                    <span className="text-xs font-semibold text-secondary">What came back</span>
                    <code className="block whitespace-pre-wrap break-words rounded bg-surface-secondary p-2 text-xs text-danger">
                        {call.error_message}
                    </code>
                </div>
            ) : null}
        </LemonCard>
    )
}
