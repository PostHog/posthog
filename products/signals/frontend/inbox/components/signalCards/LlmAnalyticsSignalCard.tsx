import { BindLogic, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
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
import { llmTraceMetrics, llmTracePreviewText } from './signalCardParsing'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

// ── Shared link-out ────────────────────────────────────────────────────────────────

function ExternalSignalLink({ to, label }: { to: string; label: string }): JSX.Element {
    return (
        <Link to={to} target="_blank" className="flex items-center gap-1 text-xs font-medium shrink-0">
            {label} <IconExternal className="size-3" />
        </Link>
    )
}

// Plain "model · provider" fallback line shown while the trace loads or when it failed to load.
function ModelProviderLine({ model, provider }: { model?: string; provider?: string }): JSX.Element | null {
    const parts = [model, provider].filter(Boolean)
    if (parts.length === 0) {
        return null
    }
    return <div className="text-xs text-tertiary">{parts.join(' · ')}</div>
}

// ── Trace card (source_type: evaluation) ──────────────────────────────────────────

/** Metric strip rendered once the trace loads. Each metric is guarded — missing fields are skipped. */
function TraceMetricStrip({ extra }: { extra: LlmEvalSignalExtraApi }): JSX.Element | null {
    const { trace, traceLoading } = useValues(inboxLlmTraceLogic)

    if (traceLoading) {
        return <LemonSkeleton className="h-4 w-48" />
    }

    if (!trace) {
        return <ModelProviderLine model={extra.model ?? undefined} provider={extra.provider ?? undefined} />
    }

    const provider = normalizeLLMProvider(extra.provider ?? undefined)
    const metrics = llmTraceMetrics(trace)

    if (metrics.length === 0 && !extra.model && !provider) {
        return <></>
    }

    return (
        <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary">
            {provider && (
                <span className="inline-flex items-center shrink-0">
                    <LLMProviderIcon provider={provider} className="size-3.5" />
                </span>
            )}
            {extra.model && <span className="font-medium text-secondary">{extra.model}</span>}
            {metrics.length > 0 && (
                <span className="flex items-center gap-2">
                    {metrics.map((metric, index) => (
                        <span key={index} className="flex items-center gap-2">
                            {index > 0 && <span className="text-border">·</span>}
                            <span>{metric}</span>
                        </span>
                    ))}
                </span>
            )}
        </div>
    )
}

// 2-line preview derived from the trace's input/output state (or null while loading / on failure).
function TracePreview(): JSX.Element | null {
    const { trace } = useValues(inboxLlmTraceLogic)

    if (!trace) {
        return null
    }

    const previewText = llmTracePreviewText(trace)

    if (!previewText) {
        return null
    }

    return <div className="text-xs text-tertiary line-clamp-2 mt-1 whitespace-pre-wrap break-words">{previewText}</div>
}

function LlmEvalTraceSignalCardBody({
    signal,
    extra,
}: {
    signal: SignalNode
    extra: LlmEvalSignalExtraApi
}): JSX.Element {
    return (
        <SignalCardShell signal={signal}>
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            <TraceMetricStrip extra={extra} />
            <TracePreview />

            <div className="flex items-center gap-3 mt-2">
                <ExternalSignalLink
                    to={urls.aiObservabilityTrace(extra.trace_id, { event: extra.target_event_id ?? undefined })}
                    label="View trace"
                />
                <ExternalSignalLink to={urls.aiObservabilityEvaluation(extra.evaluation_id)} label="View evaluation" />
            </div>
        </SignalCardShell>
    )
}

export function LlmEvalTraceSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as unknown as LlmEvalSignalExtraApi
    return (
        <BindLogic logic={inboxLlmTraceLogic} props={{ traceId: extra.trace_id }}>
            <LlmEvalTraceSignalCardBody signal={signal} extra={extra} />
        </BindLogic>
    )
}

// ── Report card (source_type: evaluation_report) ──────────────────────────────────

export function LlmEvalReportSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as unknown as LlmEvalReportSignalExtraApi

    return (
        <SignalCardShell signal={signal}>
            <div className="text-sm font-semibold text-primary">{extra.evaluation_name}</div>
            {extra.evaluation_description && (
                <div className="text-xs text-secondary line-clamp-2 mt-0.5">{extra.evaluation_description}</div>
            )}

            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mt-2 mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            <div className="text-xs text-tertiary mt-1">
                Run · {humanFriendlyDetailedTime(extra.period_start)} to {humanFriendlyDetailedTime(extra.period_end)}
            </div>

            <div className="mt-2">
                <ExternalSignalLink to={urls.aiObservabilityEvaluation(extra.evaluation_id)} label="View evaluation" />
            </div>
        </SignalCardShell>
    )
}
