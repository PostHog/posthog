import { Badge } from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

import { formatMs } from '../dashboard/formatters'
import { HarnessLogo } from '../dashboard/harness'
import type { ExampleCall, ExampleKind } from './toolReportQueries'

const KIND_BADGES: Record<ExampleKind, { label: string; variant: 'destructive' | 'warning' | 'success' }> = {
    errored: { label: 'Errored', variant: 'destructive' },
    slow: { label: 'Slow', variant: 'warning' },
    succeeded: { label: 'Succeeded', variant: 'success' },
}

export function ExampleCallRow({
    call,
    kinds,
    onOpen,
}: {
    call: ExampleCall
    /** Why the call is in the list. A call can be both slow and errored. */
    kinds: ExampleKind[]
    onOpen: (call: ExampleCall) => void
}): JSX.Element {
    const canOpen = !!call.sessionId
    const errored = kinds.includes('errored')
    return (
        <button
            type="button"
            disabled={!canOpen}
            onClick={() => onOpen(call)}
            title={canOpen ? 'Open this call in its session' : 'This call has no session to open'}
            // Intents and error messages are raw event data, so keep them out of autocapture and replay.
            className="ph-no-capture flex w-full items-start justify-between gap-3 px-3 py-2 text-left enabled:cursor-pointer enabled:hover:bg-fill-highlight-50"
            data-attr="mcp-tool-example-call"
        >
            <Tooltip title={call.client || call.harness || 'Unknown client'}>
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded border border-primary bg-surface-primary">
                    <HarnessLogo category={call.harness || 'Other'} label={call.client} className="size-4" />
                </span>
            </Tooltip>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                {call.tool ? <span className="font-mono text-sm font-semibold">{call.tool}</span> : null}
                <span className={cn('line-clamp-1 text-sm', !call.intent && 'italic text-secondary')}>
                    {call.intent || 'No intent recorded'}
                </span>
                {errored && call.errorMessage ? (
                    <span className="line-clamp-1 font-mono text-xs text-danger">{call.errorMessage}</span>
                ) : null}
                <span className="flex flex-wrap items-center gap-1.5 text-xs text-secondary">
                    {kinds.map((kind) => (
                        <Badge key={kind} variant={KIND_BADGES[kind].variant}>
                            {KIND_BADGES[kind].label}
                        </Badge>
                    ))}
                    {errored && call.errorType ? (
                        <Badge className="font-mono" translate="no">
                            {call.errorType}
                        </Badge>
                    ) : null}
                    <TZLabel time={call.timestamp} />
                </span>
            </span>
            <span className="shrink-0 text-sm tabular-nums">
                {call.durationMs !== null ? formatMs(call.durationMs) : '–'}
            </span>
        </button>
    )
}
