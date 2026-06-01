import { IconRewindPlay, IconSparkles, IconWarning } from '@posthog/icons'
import { LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { colonDelimitedDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

import type { ReplayObservationApi, ScannerSnapshotApi } from '../generated/api.schemas'
import {
    failureKindDescription,
    parseFailureReason,
    parseIneligibleReason,
    scannerTypeLabel,
} from '../replay_scanners/types'

export function ObservationStatusTag({ status }: { status: ReplayObservationApi['status'] }): JSX.Element {
    if (status === 'succeeded') {
        return <LemonTag type="success">Succeeded</LemonTag>
    }
    if (status === 'failed') {
        return <LemonTag type="danger">Failed</LemonTag>
    }
    if (status === 'ineligible') {
        // Muted, not danger — the session was skipped at the gate, not a scanner failure.
        return <LemonTag type="muted">Ineligible</LemonTag>
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

type Segment = { kind: 'text'; value: string } | { kind: 'chip'; uuid: string; timestamp_ms: number }

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
        return typeof chip.uuid === 'string' && typeof chip.timestamp_ms === 'number'
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
                        <Link key={i} onClick={() => onSeek(segment.timestamp_ms)}>
                            <IconRewindPlay className="inline-block align-text-bottom mr-0.5" />
                            <span className="font-mono">{label}</span>
                        </Link>
                    )
                }
                return (
                    <span key={i} className="text-muted font-mono">
                        {label}
                    </span>
                )
            })}
        </>
    )
}

export function readConfig(snapshot: ScannerSnapshotApi | null): Record<string, unknown> {
    const config = snapshot?.scanner_config
    return config && typeof config === 'object' ? (config as Record<string, unknown>) : {}
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
    const config = readConfig(snapshot)
    const prompt = showPrompt && typeof config.prompt === 'string' ? config.prompt : null
    const summaryClass = expandSummary ? 'text-sm whitespace-pre-wrap' : compact ? 'text-sm truncate' : 'text-sm'
    const bodyClass = compact ? 'text-sm truncate' : 'text-sm'
    const promptClass = 'text-xs text-muted'

    if (scannerType === 'monitor') {
        const verdict = Boolean(result.verdict)
        return (
            <div className="flex flex-col gap-1">
                <LemonTag size="medium" type={verdict ? 'success' : 'default'} className="self-start">
                    {verdict ? 'Yes' : 'No'}
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
        const empty = fixedTags.length === 0 && freeformTags.length === 0
        const renderFixed = (): JSX.Element[] =>
            fixedTags.map((tag) => (
                <LemonTag key={`fixed-${tag}`} size="medium" type="option" title="From the configured tag list">
                    {tag}
                </LemonTag>
            ))
        const renderFreeform = (): JSX.Element[] =>
            freeformTags.map((tag) => (
                <LemonTag
                    key={`freeform-${tag}`}
                    size="medium"
                    type="default"
                    icon={<IconSparkles />}
                    title="Free-form tag from the model"
                >
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
                                {renderFixed()}
                                {renderFreeform()}
                            </>
                        )}
                    </div>
                    {prompt && <span className={promptClass}>{prompt}</span>}
                </div>
            )
        }
        if (empty) {
            return (
                <div className="flex flex-col gap-1">
                    <span className="text-muted text-sm">No tags</span>
                    {prompt && <span className={promptClass}>{prompt}</span>}
                </div>
            )
        }
        return (
            <div className="flex flex-col gap-3">
                {fixedTags.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                        <div className="text-xs font-medium uppercase tracking-wide text-muted">Fixed</div>
                        <p className="text-xs text-muted m-0">Tags from the scanner's configured list.</p>
                        <div className="flex flex-wrap gap-1">{renderFixed()}</div>
                    </div>
                )}
                {freeformTags.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                        <div className="flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted">
                            <IconSparkles className="text-sm" />
                            <span>Freeform</span>
                        </div>
                        <p className="text-xs text-muted m-0">Emitted by the model outside the configured tags.</p>
                        <div className="flex flex-wrap gap-1">{renderFreeform()}</div>
                    </div>
                )}
                {prompt && <span className={promptClass}>{prompt}</span>}
            </div>
        )
    }

    if (scannerType === 'scorer') {
        const score = typeof result.score === 'number' ? result.score : null
        const resultLabel = typeof result.label === 'string' ? result.label : null
        const scale =
            config.scale && typeof config.scale === 'object' ? (config.scale as Record<string, unknown>) : null
        const scaleMax = scale && typeof scale.max === 'number' ? scale.max : null
        const scaleLabel = scale && typeof scale.label === 'string' ? scale.label : null
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
    if (observation.status === 'ineligible') {
        const parsed = parseIneligibleReason(observation.error_reason)
        const label = parsed?.label ?? 'Ineligible'
        const detail = parsed?.message ?? observation.error_reason
        return (
            <Tooltip title={detail || label}>
                <span className="text-muted text-sm">{label}</span>
            </Tooltip>
        )
    }
    if (observation.status === 'failed') {
        const parsed = parseFailureReason(observation.error_reason)
        const label = parsed?.label ?? 'Failed'
        const description = parsed ? failureKindDescription(parsed.kind) : null
        const detail = parsed?.message ?? observation.error_reason
        const tooltip = [description, detail].filter(Boolean).join('\n\n') || 'Unknown error'
        return (
            <Tooltip title={tooltip}>
                <span className="inline-flex items-center gap-1 text-danger text-sm">
                    <IconWarning /> {label}
                </span>
            </Tooltip>
        )
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

function ObservationProgress({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-muted text-sm">
            <Spinner textColored />
            <span>{observation.status === 'pending' ? 'Queued…' : 'Analyzing recording…'}</span>
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
                    <ObservationStatusTag status={observation.status} />
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
                <ObservationProgress observation={observation} />
            )}
        </div>
    )
}
