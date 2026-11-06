import { IconCopy, IconSparkles } from '@posthog/icons'
import { Badge, Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { type ClassifierScannerConfig, type ScorerScannerConfig, configFromSnapshot } from '../replay_scanners/types'
import { citedTextToPlainText } from '../utils/citations'
import { VERDICT_LABEL, isSummaryScannerType, readReasoning } from '../utils/observation'
import { readResult } from './ObservationCard'
import { QuillCitedText } from './QuillCitedText'

function WithReasoning({ tooltip, children }: { tooltip: string | null; children: JSX.Element }): JSX.Element {
    if (!tooltip) {
        return children
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="flex self-start" />}>{children}</TooltipTrigger>
            <TooltipContent className="max-w-96 whitespace-pre-wrap">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

export function QuillObservationPrimaryOutput({
    observation,
    compact = false,
    showPrompt = true,
    onSeek,
    expandSummary = false,
    copyable = false,
    reasoningTooltip = false,
}: {
    observation: ReplayObservationApi
    compact?: boolean
    showPrompt?: boolean
    /** Called with timestamp_ms when a citation chip is clicked. If omitted, citations render as plain text. */
    onSeek?: (timestampMs: number) => void
    /** When true, summarizer body wraps in full; when false, single-line truncate. */
    expandSummary?: boolean
    /** Shows a copy button on summarizer output with citations as plain timestamps. */
    copyable?: boolean
    /** Hovering the result shows its reasoning, for rows with nowhere else to print it. */
    reasoningTooltip?: boolean
}): JSX.Element | null {
    const snapshot = observation.scanner_snapshot
    const result = readResult(observation)
    if (!snapshot || !result) {
        return null
    }
    const scannerType = snapshot.scanner_type
    const config = configFromSnapshot(snapshot)
    const prompt = showPrompt ? (config?.prompt ?? null) : null
    const reasoning = reasoningTooltip ? readReasoning(observation) : null
    const resultTooltip = reasoning ? citedTextToPlainText(reasoning, result.reasoning_segments) : null
    const summaryClass = expandSummary ? 'text-sm whitespace-pre-wrap' : compact ? 'text-sm truncate' : 'text-sm'
    const promptLine = prompt ? <span className="text-xs text-muted-foreground">{prompt}</span> : null

    if (scannerType === 'monitor') {
        const verdict = result.verdict
        const known = verdict === 'yes' || verdict === 'no' || verdict === 'inconclusive'
        return (
            <div className="flex flex-col gap-1">
                <WithReasoning tooltip={resultTooltip}>
                    {/* Neutral accent, not success-green: a "yes" verdict isn't inherently good. */}
                    <Badge
                        variant={verdict === 'yes' ? 'info' : 'default'}
                        className={verdict === 'no' ? undefined : known ? undefined : 'opacity-70'}
                    >
                        {known ? VERDICT_LABEL[verdict] : '—'}
                    </Badge>
                </WithReasoning>
                {promptLine}
            </div>
        )
    }

    if (isSummaryScannerType(scannerType)) {
        const title = typeof result.title === 'string' ? result.title : null
        const summary = typeof result.summary === 'string' ? result.summary : null
        const showCopy = copyable && summary !== null
        return (
            <div className="flex flex-col gap-1">
                {(title || showCopy) && (
                    <div className="flex items-start justify-between gap-2">
                        {title && <span className="font-semibold text-sm">{title}</span>}
                        {showCopy && (
                            <Button
                                size="icon-xs"
                                tooltip="Copy summary"
                                aria-label="Copy summary"
                                className="ml-auto -my-1"
                                onClick={() =>
                                    void copyToClipboard(
                                        [title, citedTextToPlainText(summary, result.summary_segments)]
                                            .filter(Boolean)
                                            .join('\n\n'),
                                        'summary'
                                    )
                                }
                                data-attr="vision-copy-summary"
                            >
                                <IconCopy />
                            </Button>
                        )}
                    </div>
                )}
                {summary && (
                    <span className={summaryClass}>
                        <QuillCitedText text={summary} segments={result.summary_segments} onSeek={onSeek} />
                    </span>
                )}
            </div>
        )
    }

    if (scannerType === 'classifier') {
        const fixedTags = Array.isArray(result.tags) ? (result.tags as string[]) : []
        const freeformTags = Array.isArray(result.tags_freeform) ? (result.tags_freeform as string[]) : []
        const configuredTags = Array.isArray((config as ClassifierScannerConfig | null)?.tags)
            ? (config as ClassifierScannerConfig).tags
            : []
        const chosen = new Set(fixedTags)
        const empty = fixedTags.length === 0 && freeformTags.length === 0
        const freeform = freeformTags.map((tag, index) => (
            <Badge key={`freeform-${index}-${tag}`} className="gap-1">
                <IconSparkles />
                {tag}
            </Badge>
        ))
        if (compact || (configuredTags.length === 0 && empty)) {
            return (
                <div className="flex flex-col gap-1">
                    <div className="flex flex-wrap gap-1">
                        {empty ? (
                            <span className="text-muted-foreground text-sm">No categories</span>
                        ) : (
                            <>
                                {fixedTags.map((tag, index) => (
                                    <Badge key={`fixed-${index}-${tag}`} variant="info">
                                        {tag}
                                    </Badge>
                                ))}
                                {freeform}
                            </>
                        )}
                    </div>
                    {promptLine}
                </div>
            )
        }
        return (
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-1">
                    {configuredTags.map((tag, index) => (
                        <Badge
                            key={`fixed-${index}-${tag}`}
                            variant={chosen.has(tag) ? 'info' : 'default'}
                            className={chosen.has(tag) ? undefined : 'opacity-50 line-through'}
                        >
                            {tag}
                        </Badge>
                    ))}
                    {freeform}
                </div>
                {promptLine}
            </div>
        )
    }

    if (scannerType === 'scorer') {
        const score = typeof result.score === 'number' ? result.score : null
        const resultLabel = typeof result.label === 'string' ? result.label : null
        const scale = (config as ScorerScannerConfig | null)?.scale ?? null
        const scaleMax = typeof scale?.max === 'number' ? scale.max : null
        const scaleLabel = typeof scale?.label === 'string' ? scale.label : null
        // The per-observation label is specific; the configured scale label is the axis name.
        const displayLabel = resultLabel ?? scaleLabel
        return (
            <div className="flex flex-col gap-1">
                <WithReasoning tooltip={resultTooltip}>
                    <span className="text-sm self-start">
                        <span className="font-semibold text-base">{score ?? '—'}</span>
                        {scaleMax !== null && <span className="text-muted-foreground"> / {scaleMax}</span>}
                        {displayLabel && <span className="text-muted-foreground"> — {displayLabel}</span>}
                    </span>
                </WithReasoning>
                {promptLine}
            </div>
        )
    }

    const summary = typeof result.summary === 'string' ? result.summary : null
    const userType = typeof result.user_type === 'string' ? result.user_type : null
    return (
        <div className="flex flex-col gap-1">
            {summary && <span className={compact ? 'text-sm truncate' : 'text-sm'}>{summary}</span>}
            {userType && (
                <span className="text-muted-foreground text-xs">
                    <span className="font-medium">User: </span>
                    {userType}
                </span>
            )}
        </div>
    )
}
