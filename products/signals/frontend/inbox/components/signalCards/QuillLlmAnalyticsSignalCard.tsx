import { BindLogic, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { Skeleton, Text } from '@posthog/quill'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import type { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { LLMProviderIcon } from 'products/ai_observability/frontend/LLMProviderIcon'
import { normalizeLLMProvider } from 'products/ai_observability/frontend/settings/llmProviderKeysLogic'
import type {
    LlmEvalReportSignalExtraApi,
    LlmEvalSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'

import { inboxLlmTraceLogic } from './inboxLlmTraceLogic'
import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { llmTraceMetrics, llmTracePreviewText } from './signalCardParsing'
import type { SignalCardProps } from './types'

// ── Trace card (source_type: evaluation) ──────────────────────────────────────────

/** Metric strip rendered once the trace loads, or a plain "model · provider" line while it loads or when it failed. */
function QuillTraceMetricStrip({ extra }: { extra: LlmEvalSignalExtraApi }): JSX.Element | null {
    const { trace, traceLoading } = useValues(inboxLlmTraceLogic)

    if (traceLoading) {
        return <Skeleton className="h-4 w-48 max-w-full" />
    }

    if (!trace) {
        const parts = [extra.model, extra.provider].filter(Boolean)
        return parts.length > 0 ? (
            <Text size="xs" variant="muted" className="m-0">
                {parts.join(' · ')}
            </Text>
        ) : null
    }

    const provider = normalizeLLMProvider(extra.provider ?? undefined)
    const metrics = llmTraceMetrics(trace)

    if (metrics.length === 0 && !extra.model && !provider) {
        return null
    }

    return (
        <Text size="xs" variant="muted" render={<div />} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {provider && (
                <span className="inline-flex shrink-0 items-center">
                    <LLMProviderIcon provider={provider} className="size-3.5" />
                </span>
            )}
            {extra.model && <span className="font-medium text-foreground">{extra.model}</span>}
            {metrics.map((metric, index) => (
                <span key={index} className="flex items-center gap-2">
                    {index > 0 && <span className="text-subtle-foreground">·</span>}
                    <span>{metric}</span>
                </span>
            ))}
        </Text>
    )
}

// 2-line preview derived from the trace's input/output state (or null while loading / on failure).
function QuillTracePreview(): JSX.Element | null {
    const { trace } = useValues(inboxLlmTraceLogic)

    const previewText = trace ? llmTracePreviewText(trace) : ''
    if (!previewText) {
        return null
    }

    return (
        <Text size="xs" variant="muted" className="m-0 line-clamp-2 whitespace-pre-wrap break-words">
            {previewText}
        </Text>
    )
}

function QuillLlmEvalTraceSignalCardBody({
    signal,
    extra,
}: {
    signal: SignalNode
    extra: LlmEvalSignalExtraApi
}): JSX.Element {
    return (
        <QuillSignalCardShell signal={signal}>
            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}

            <div className="flex flex-col gap-1">
                <QuillTraceMetricStrip extra={extra} />
                <QuillTracePreview />
            </div>

            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <QuillSignalCardLink
                    to={urls.aiObservabilityTrace(extra.trace_id, { event: extra.target_event_id ?? undefined })}
                    newTab
                >
                    View trace
                    <IconExternal />
                </QuillSignalCardLink>
                <QuillSignalCardLink to={urls.aiObservabilityEvaluation(extra.evaluation_id)} newTab>
                    View evaluation
                    <IconExternal />
                </QuillSignalCardLink>
            </div>
        </QuillSignalCardShell>
    )
}

export function QuillLlmEvalTraceSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as unknown as LlmEvalSignalExtraApi
    return (
        <BindLogic logic={inboxLlmTraceLogic} props={{ traceId: extra.trace_id }}>
            <QuillLlmEvalTraceSignalCardBody signal={signal} extra={extra} />
        </BindLogic>
    )
}

// ── Report card (source_type: evaluation_report) ──────────────────────────────────

export function QuillLlmEvalReportSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as unknown as LlmEvalReportSignalExtraApi

    return (
        <QuillSignalCardShell signal={signal}>
            <div className="flex flex-col gap-0.5">
                <Text size="sm" weight="semibold" className="m-0 break-words">
                    {extra.evaluation_name}
                </Text>
                {extra.evaluation_description && (
                    <Text size="xs" variant="muted" className="m-0 line-clamp-2">
                        {extra.evaluation_description}
                    </Text>
                )}
            </div>

            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}

            <Text size="xs" variant="muted" className="m-0">
                Run · {humanFriendlyDetailedTime(extra.period_start)} to {humanFriendlyDetailedTime(extra.period_end)}
            </Text>

            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <QuillSignalCardLink to={urls.aiObservabilityEvaluation(extra.evaluation_id)} newTab>
                    View evaluation
                    <IconExternal />
                </QuillSignalCardLink>
            </div>
        </QuillSignalCardShell>
    )
}
