import type { ReactNode } from 'react'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonCard } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { BrandMark } from '../components/BrandMark'
import { harnessMark } from '../dashboard/harnessRegistry'
import type { MCPActivityRecentCallApi } from '../generated/api.schemas'
import { formatDuration } from '../sessions/utils'
import { callClientLabel } from './callClient'

const COPY = {
    called: (client: string) => `${client} called`,
    intent: 'What the agent was trying to do',
    status: 'Status',
    ok: 'OK',
    failed: 'Failed',
    latency: 'Latency',
    response: 'What came back',
}

function Stat({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-0.5">
            <dt className="text-xs font-semibold text-secondary">{label}</dt>
            <dd className="m-0 flex items-center gap-1.5 text-2xl font-semibold">{children}</dd>
        </div>
    )
}

/** The newest tool call, shown large: the moment the user first sees their own data. */
export function ToolCallHeroCard({ call }: { call: MCPActivityRecentCallApi }): JSX.Element {
    const client = callClientLabel(call)
    return (
        <LemonCard
            hoverEffect={false}
            className={cn('flex flex-col gap-5 p-5 @min-[36rem]/setup-mode:p-6', call.is_error && 'border-danger')}
            data-attr="mcp-analytics-setup-mode-call"
        >
            <div className="flex items-start gap-3">
                <span className="flex size-12 shrink-0 items-center justify-center rounded border border-primary bg-surface-secondary">
                    <BrandMark name={harnessMark(client)} className="size-7" />
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                    <span className="text-sm text-secondary">{COPY.called(client)}</span>
                    <span className="truncate font-mono text-2xl font-semibold">{call.tool}</span>
                </div>
                <span className="shrink-0 text-xs text-secondary">
                    <TZLabel time={call.timestamp} />
                </span>
            </div>
            {call.intent ? (
                <figure className="m-0 flex flex-col gap-1.5">
                    <figcaption className="text-xs font-semibold text-secondary">{COPY.intent}</figcaption>
                    <blockquote className="m-0 border-l-4 border-primary pl-4 text-xl leading-snug">
                        “{call.intent}”
                    </blockquote>
                </figure>
            ) : null}
            <dl className="m-0 flex flex-wrap gap-x-10 gap-y-3 border-t border-primary pt-4">
                <Stat label={COPY.status}>
                    {call.is_error ? (
                        <>
                            <IconWarning className="text-danger" />
                            <span className="text-danger">{COPY.failed}</span>
                        </>
                    ) : (
                        <>
                            <IconCheckCircle className="text-success" />
                            <span className="text-success">{COPY.ok}</span>
                        </>
                    )}
                </Stat>
                {call.duration_ms !== null ? (
                    <Stat label={COPY.latency}>{formatDuration(Math.round(call.duration_ms))}</Stat>
                ) : null}
            </dl>
            {call.is_error && call.error_message ? (
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold text-secondary">{COPY.response}</span>
                    <code className="block whitespace-pre-wrap break-words rounded border border-danger bg-fill-error-highlight p-3 text-sm text-danger">
                        {call.error_message}
                    </code>
                </div>
            ) : null}
        </LemonCard>
    )
}
