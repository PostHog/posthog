import { IconRewindPlay, IconSparkles } from '@posthog/icons'
import { LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { colonDelimitedDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    type ClassifierScannerConfig,
    type ScorerScannerConfig,
    configFromSnapshot,
    failureKindDescription,
    ineligibleKindDescription,
    parseFailureReason,
    parseIneligibleReason,
    scannerTypeLabel,
} from '../replay_scanners/types'
import { ObservationProgressBar } from './ObservationProgressBar'

export function ObservationStatusTag({
    status,
    errorReason,
}: {
    status: ReplayObservationApi['status']
    errorReason?: string | null
}): JSX.Element {
    if (status === 'succeeded') {
        return <LemonTag type="success">Succeeded</LemonTag>
    }
    if (status === 'failed') {
        // Raw exception text lives in `FailureDetail`; tooltip is the description only.
        const parsed = errorReason ? parseFailureReason(errorReason) : null
        const tooltip = parsed ? failureKindDescription(parsed.kind) : errorReason || null
        return (
            <Tooltip title={tooltip}>
                <LemonTag type="danger">Failed</LemonTag>
            </Tooltip>
        )
    }
    if (status === 'ineligible') {
        // Muted, not danger — the session was skipped at the gate, not a scanner failure.
        const parsed = errorReason ? parseIneligibleReason(errorReason) : null
        const tooltip = parsed ? (
            <div className="flex flex-col gap-1">
                <div>{ineligibleKindDescription(parsed.kind)}</div>
                {parsed.message && <div className="text-xs opacity-80">{parsed.message}</div>}
            </div>
        ) : errorReason ? (
            <div>{errorReason}</div>
        ) : null
        return (
            <Tooltip title={tooltip}>
                <LemonTag type="muted">Ineligible</LemonTag>
            </Tooltip>
        )
    }
    if (status === 'running') {
        return (
            <LemonTag type="warning">
                <Spinner className="mr-1" /> Running
            </LemonTag>
        )
    }
    return <LemonTag type="default">Pending</LemonTag>
}

export function readResult(observation: ReplayObservationApi): Record<string, unknown> | null {
    const output = observation.scanner_result?.model_output
    return output && typeof output === 'object' ? (output as Record<string, unknown>) : null
}

// `uuid` is legacy — only old event-uuid citations carry it; timestamp citations use `timestamp_ms` alone.
type Segment = { kind: 'text'; value: string } | { kind: 'chip'; timestamp_ms: number; uuid?: string }

function isSegment(value: unknown): value is Segment {
    if (!value || typeof value !== 'object') {
        return false
    }
    const candidate = value as Partial<Segment>
    if (candidate.kind === 'text') {
        return typeof (candidate as { value?: unknown }).value === 'string'
    }
    if (candidate.kind === 'chip') {
        const chip = candidate as Partial<Extract<Segment, { kind: 'chip' }>>
        return typeof chip.timestamp_ms === 'number'
    }
    return false
}

/** Dumb renderer for parsed citation segments. Pass `onSeek` to make citation chips interactive; omit for plain-text timestamps. */
export function CitedText({
    text,
    segments,
    onSeek,
}: {
    text: string
    segments: unknown
    onSeek?: (timestampMs: number) => void
}): JSX.Element {
    const list = Array.isArray(segments) ? (segments.filter(isSegment) as Segment[]) : []
    if (list.length === 0) {
        return <>{text}</>
    }
    return (
        <>
            {list.map((segment, i) => {
                if (segment.kind === 'text') {
                    return <span key={i}>{segment.value}</span>
                }
                const seconds = Math.max(0, Math.floor(segment.timestamp_ms / 1000))
                const label = colonDelimitedDuration(seconds, null)
                if (onSeek) {
                    return (
                        <Link key={i} onClick={() => onSeek(segment.timestamp_ms)} className="ml-0.5">
                            <IconRewindPlay className="inline-block align-text-bottom mr-0.5" />
                            <span className="font-mono">{label}</span>
                        </Link>
                    )
                }
                return (
                    <span key={i} className="text-muted font-mono ml-0.5">
                        {label}
                    </span>
                )
            })}
        </>
    )
}

export function ObservationPrimaryOutput({
    observation,
    compact = false,
    showPrompt = true,
    onSeek,
    expandSummary = false,
}: {
    observation: ReplayObservationApi
    compact?: boolean
    showPrompt?: boolean
    /** Called with timestamp_ms when a citation chip is clicked. If omitted, citations render as plain text. */
    onSeek?: (timestampMs: number) => void
    /** When true (dock/detail), summarizer body wraps in full; when false (table), single-line truncate. */
    expandSummary?: boolean
}): JSX.Element | null {
    const snapshot = observation.scanner_snapshot
    const result = readResult(observation)
    if (!snapshot || !result) {
        return null
    }
    const scannerType = snapshot.scanner_type
    const config = configFromSnapshot(snapshot)
    const prompt = showPrompt ? (config?.prompt ?? null) : null
    const summaryClass = expandSummary ? 'text-sm whitespace-pre-wrap' : compact ? 'text-sm truncate' : 'text-sm'
    const bodyClass = compact ? 'text-sm truncate' : 'text-sm'
    const promptClass = 'text-xs text-muted'

    if (scannerType === 'monitor') {
        const verdict = result.verdict
        // Neutral accent, not success-green: a "yes" verdict isn't inherently good.
        const tagType =
            verdict === 'yes'
                ? 'highlight'
                : verdict === 'no'
                  ? 'default'
                  : verdict === 'inconclusive'
                    ? 'muted'
                    : 'muted'
        const tagLabel =
            verdict === 'yes' ? 'Yes' : verdict === 'no' ? 'No' : verdict === 'inconclusive' ? 'Inconclusive' : '—'
        return (
            <div className="flex flex-col gap-1">
                <LemonTag size="medium" type={tagType} className="self-start">
                    {tagLabel}
                </LemonTag>
                {prompt && <span className={promptClass}>{prompt}</span>}
            </div>
        )
    }

    if (scannerType === 'summarizer') {
        const title = typeof result.title === 'string' ? result.title : null
        const summary = typeof result.summary === 'string' ? result.summary : null
        return (
            <div className="flex flex-col gap-1">
                {title && <span className="font-semibold text-sm">{title}</span>}
                {summary && (
                    <span className={summaryClass}>
                        <CitedText text={summary} segments={result.summary_segments} onSeek={onSeek} />
                    </span>
                )}
            </div>
        )
    }

    if (scannerType === 'classifier') {
        const fixedTags = Array.isArray(result.tags) ? (result.tags as string[]) : []
        const freeformTags = Array.isArray(result.tags_freeform) ? (result.tags_freeform as string[]) : []
        const classifierConfig = config as ClassifierScannerConfig | null
        const configuredTags = Array.isArray(classifierConfig?.tags) ? classifierConfig.tags : []
        const chosen = new Set(fixedTags)
        const empty = fixedTags.length === 0 && freeformTags.length === 0
        const renderVocab = (): JSX.Element[] =>
            configuredTags.map((tag, index) => {
                const isChosen = chosen.has(tag)
                return (
                    <LemonTag
                        key={`fixed-${index}-${tag}`}
                        size="medium"
                        type={isChosen ? 'option' : 'default'}
                        className={isChosen ? undefined : 'opacity-50 line-through'}
                    >
                        {tag}
                    </LemonTag>
                )
            })
        const renderFreeform = (): JSX.Element[] =>
            freeformTags.map((tag, index) => (
                <LemonTag key={`freeform-${index}-${tag}`} size="medium" type="default" icon={<IconSparkles />}>
                    {tag}
                </LemonTag>
            ))
        if (compact) {
            return (
                <div className="flex flex-col gap-1">
                    <div className="flex flex-wrap gap-1">
                        {empty ? (
                            <span className="text-muted text-sm">No tags</span>
                        ) : (
                            <>
                                {fixedTags.map((tag, index) => (
                                    <LemonTag key={`fixed-${index}-${tag}`} size="medium" type="option">
                                        {tag}
                                    </LemonTag>
                                ))}
                                {renderFreeform()}
                            </>
                        )}
                    </div>
                    {prompt && <span className={promptClass}>{prompt}</span>}
                </div>
            )
        }
        if (configuredTags.length === 0 && empty) {
            return (
                <div className="flex flex-col gap-1">
                    <span className="text-muted text-sm">No tags</span>
                    {prompt && <span className={promptClass}>{prompt}</span>}
                </div>
            )
        }
        return (
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-1">
                    {renderVocab()}
                    {renderFreeform()}
                </div>
                {prompt && <span className={promptClass}>{prompt}</span>}
            </div>
        )
    }

    if (scannerType === 'scorer') {
        const score = typeof result.score === 'number' ? result.score : null
        const resultLabel = typeof result.label === 'string' ? result.label : null
        const scale = (config as ScorerScannerConfig | null)?.scale ?? null
        const scaleMax = typeof scale?.max === 'number' ? scale.max : null
        const scaleLabel = typeof scale?.label === 'string' ? scale.label : null
        // Prefer the per-observation label (specific); fall back to the configured scale label (axis name).
        const displayLabel = resultLabel ?? scaleLabel
        return (
            <div className="flex flex-col gap-1">
                <span className="text-sm">
                    <span className="font-semibold text-base">{score ?? '—'}</span>
                    {scaleMax !== null && <span className="text-muted"> / {scaleMax}</span>}
                    {displayLabel && <span className="text-muted"> — {displayLabel}</span>}
                </span>
                {prompt && <span className={promptClass}>{prompt}</span>}
            </div>
        )
    }

    // Unknown / generic fallback (also covers summarizers that emit facets alongside title/summary).
    const summary = typeof result.summary === 'string' ? result.summary : null
    const userType = typeof result.user_type === 'string' ? result.user_type : null
    const outcome = typeof result.outcome === 'string' ? result.outcome : null
    const keywords = Array.isArray(result.keywords) ? (result.keywords as string[]) : []
    return (
        <div className="flex flex-col gap-1">
            {summary && <span className={bodyClass}>{summary}</span>}
            {userType && (
                <span className="text-muted text-xs">
                    <span className="font-medium">User: </span>
                    {userType}
                </span>
            )}
            {outcome && (
                <span className="text-muted text-xs">
                    <span className="font-medium">Outcome: </span>
                    {outcome}
                </span>
            )}
            {keywords.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {keywords.map((keyword) => (
                        <LemonTag key={keyword} type="option" size="small">
                            {keyword}
                        </LemonTag>
                    ))}
                </div>
            )}
        </div>
    )
}

export function ObservationConfidence({ result }: { result: Record<string, unknown> }): JSX.Element | null {
    if (typeof result.confidence !== 'number') {
        return null
    }
    const value = result.confidence
    const pct = Math.round(value * 100)
    const { type, label } =
        value >= 0.8
            ? ({ type: 'success', label: 'High' } as const)
            : value >= 0.5
              ? ({ type: 'warning', label: 'Medium' } as const)
              : ({ type: 'danger', label: 'Low' } as const)
    return (
        <div className="flex items-center gap-2">
            <LemonTag type={type}>{label}</LemonTag>
            <span className="text-sm tabular-nums text-muted">{pct}%</span>
        </div>
    )
}

export function ObservationResultSummary({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    if (observation.status === 'ineligible' || observation.status === 'failed') {
        return <span className="text-muted text-sm">—</span>
    }
    const snapshot = observation.scanner_snapshot
    const result = readResult(observation)
    if (!snapshot || !result) {
        return <span className="text-muted text-sm">—</span>
    }
    return <ObservationPrimaryOutput observation={observation} compact showPrompt={false} />
}

export function FailureDetail({ errorReason }: { errorReason: string }): JSX.Element {
    const parsed = parseFailureReason(errorReason)
    if (!parsed) {
        return <div className="text-danger text-sm">{errorReason}</div>
    }
    return (
        <div className="space-y-1">
            <div className="font-semibold text-danger text-sm">{parsed.label}</div>
            <div className="text-muted text-xs">{failureKindDescription(parsed.kind)}</div>
            {parsed.message && <div className="text-muted text-xs font-mono">{parsed.message}</div>}
        </div>
    )
}

export function IneligibleDetail({ errorReason }: { errorReason: string }): JSX.Element {
    const parsed = parseIneligibleReason(errorReason)
    if (!parsed) {
        return <div className="text-muted text-sm">{errorReason}</div>
    }
    return (
        <div className="space-y-1">
            <div className="font-semibold text-sm">{parsed.label}</div>
            {parsed.message && <div className="text-muted text-xs">{parsed.message}</div>}
        </div>
    )
}

export function ObservationDockCard({
    observation,
    onSeek,
}: {
    observation: ReplayObservationApi
    onSeek?: (timestampMs: number) => void
}): JSX.Element {
    const snapshot = observation.scanner_snapshot
    const scannerType = snapshot?.scanner_type
    const result = readResult(observation)

    return (
        <div className="border rounded p-3 bg-surface-primary space-y-2">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <ObservationStatusTag status={observation.status} errorReason={observation.error_reason} />
                    <span className="font-semibold text-sm truncate">{snapshot?.name || 'Scanner'}</span>
                    {scannerType && <span className="text-muted text-xs">{scannerTypeLabel(scannerType)}</span>}
                </div>
                <Link to={urls.replayVisionObservation(observation.id)} className="text-xs whitespace-nowrap">
                    View details
                </Link>
            </div>

            {observation.status === 'failed' && observation.error_reason && (
                <FailureDetail errorReason={observation.error_reason} />
            )}

            {observation.status === 'ineligible' && observation.error_reason && (
                <IneligibleDetail errorReason={observation.error_reason} />
            )}

            {observation.status === 'succeeded' && snapshot && result && (
                <ObservationPrimaryOutput observation={observation} compact onSeek={onSeek} expandSummary />
            )}

            {(observation.status === 'pending' || observation.status === 'running') && (
                <ObservationProgressBar observationId={observation.id} sessionId={observation.session_id} compact />
            )}
        </div>
    )
}
