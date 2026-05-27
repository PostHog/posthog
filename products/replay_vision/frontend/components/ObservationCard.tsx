import { IconWarning } from '@posthog/icons'
import { LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ScannerTypeEnumApi, ReplayObservationApi } from '../generated/api.schemas'
import { failureKindDescription, parseFailureReason, parseIneligibleReason } from '../replay_scanners/types'

const SCANNER_TYPE_LABEL: Record<ScannerTypeEnumApi, string> = {
    monitor: 'Monitor',
    classifier: 'Classifier',
    scorer: 'Scorer',
    summarizer: 'Summarizer',
    indexer: 'Indexer',
}

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

function readResult(observation: ReplayObservationApi): Record<string, unknown> | null {
    const output = observation.scanner_result?.model_output
    return output && typeof output === 'object' ? (output as Record<string, unknown>) : null
}

/** Compact, single-cell preview of an observation result for the Vision scene's observations table. */
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
    const scannerType = observation.scanner_snapshot?.scanner_type
    const result = readResult(observation)
    if (!scannerType || !result) {
        return <span className="text-muted text-sm">—</span>
    }
    return <ObservationResult scannerType={scannerType} result={result} compact />
}

function ObservationResult({
    scannerType,
    result,
    compact = false,
}: {
    scannerType: ScannerTypeEnumApi
    result: Record<string, unknown>
    compact?: boolean
}): JSX.Element {
    const reasoning = typeof result.reasoning === 'string' ? result.reasoning : null
    const reasoningClass = compact ? 'text-muted text-xs truncate' : 'text-muted text-sm'
    const bodyClass = compact ? 'text-sm truncate' : 'text-sm'

    if (scannerType === 'monitor') {
        const verdict = Boolean(result.verdict)
        return (
            <div className="flex flex-col gap-1">
                <LemonTag type={verdict ? 'success' : 'default'}>{verdict ? 'Yes' : 'No'}</LemonTag>
                {reasoning && <span className={reasoningClass}>{reasoning}</span>}
            </div>
        )
    }

    if (scannerType === 'summarizer') {
        const title = typeof result.title === 'string' ? result.title : null
        const summary = typeof result.summary === 'string' ? result.summary : null
        return (
            <div className="flex flex-col gap-1">
                {title && <span className="font-semibold text-sm">{title}</span>}
                {summary && <span className={bodyClass}>{summary}</span>}
            </div>
        )
    }

    if (scannerType === 'classifier') {
        const tags = Array.isArray(result.tags) ? (result.tags as string[]) : []
        return (
            <div className="flex flex-col gap-1">
                <div className="flex flex-wrap gap-1">
                    {tags.length === 0 ? (
                        <span className="text-muted text-sm">No tags</span>
                    ) : (
                        tags.map((tag) => (
                            <LemonTag key={tag} type="option">
                                {tag}
                            </LemonTag>
                        ))
                    )}
                </div>
                {reasoning && <span className={reasoningClass}>{reasoning}</span>}
            </div>
        )
    }

    if (scannerType === 'scorer') {
        const score = typeof result.score === 'number' ? result.score : null
        const label = typeof result.label === 'string' ? result.label : null
        return (
            <div className="flex flex-col gap-1">
                <span className="text-sm">
                    <span className="font-semibold">{score ?? '—'}</span>
                    {label && <span className="text-muted"> {label}</span>}
                </span>
                {reasoning && <span className={reasoningClass}>{reasoning}</span>}
            </div>
        )
    }

    const summary = typeof result.summary === 'string' ? result.summary : null
    const userType = typeof result.user_type === 'string' ? result.user_type : null
    const outcome = typeof result.outcome === 'string' ? result.outcome : null
    const keywords = Array.isArray(result.keywords) ? (result.keywords as string[]) : []
    return (
        <div className="flex flex-col gap-1">
            {summary && <span className={bodyClass}>{summary}</span>}
            {userType && (
                <span className={reasoningClass}>
                    <span className="font-medium">User: </span>
                    {userType}
                </span>
            )}
            {outcome && (
                <span className={reasoningClass}>
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

function FailureDetail({ errorReason }: { errorReason: string }): JSX.Element {
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

function IneligibleDetail({ errorReason }: { errorReason: string }): JSX.Element {
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

/** In-progress state for a pending/running observation. */
function ObservationProgress({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-muted text-sm">
            <Spinner textColored />
            <span>{observation.status === 'pending' ? 'Queued…' : 'Analyzing recording…'}</span>
        </div>
    )
}

/** Full observation presentation for the replay-page dock and the Vision scene's expanded rows. */
export function ObservationCard({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    const snapshot = observation.scanner_snapshot
    const scannerType = snapshot?.scanner_type
    const result = readResult(observation)
    const signalsCount = observation.scanner_result?.signals_count ?? 0

    return (
        <div className="border rounded p-3 bg-surface-primary space-y-2">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <ObservationStatusTag status={observation.status} />
                    <span className="font-semibold text-sm truncate">{snapshot?.name || 'Scanner'}</span>
                    {scannerType && <span className="text-muted text-xs">{SCANNER_TYPE_LABEL[scannerType]}</span>}
                </div>
                <TZLabel time={observation.created_at} className="text-muted text-xs whitespace-nowrap" />
            </div>

            {observation.status === 'failed' && observation.error_reason && (
                <FailureDetail errorReason={observation.error_reason} />
            )}

            {observation.status === 'ineligible' && observation.error_reason && (
                <IneligibleDetail errorReason={observation.error_reason} />
            )}

            {observation.status === 'succeeded' && scannerType && result && (
                <ObservationResult scannerType={scannerType} result={result} />
            )}

            {(observation.status === 'pending' || observation.status === 'running') && (
                <ObservationProgress observation={observation} />
            )}

            <div className="flex items-center gap-3 text-muted text-xs">
                {snapshot?.model && <span className="font-mono">{snapshot.model}</span>}
                {signalsCount > 0 && (
                    <span>
                        {signalsCount} signal{signalsCount === 1 ? '' : 's'}
                    </span>
                )}
            </div>
        </div>
    )
}
