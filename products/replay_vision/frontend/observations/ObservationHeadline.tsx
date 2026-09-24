import { IconCopy, IconSparkles } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { CitedText, ObservationPrimaryOutput, readResult } from '../components/ObservationCard'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { configFromSnapshot, type ScorerScannerConfig } from '../replay_scanners/types'
import { citedTextToPlainText } from '../utils/citations'

const PILL = 'inline-flex items-center gap-1 rounded-md border-2 px-3 py-0.5 font-bold'

const VERDICTS: Record<string, { label: string; className: string }> = {
    yes: { label: 'Yes', className: 'text-success border-success' },
    no: { label: 'No', className: 'text-danger border-danger' },
    inconclusive: { label: 'Inconclusive', className: 'text-muted border-primary' },
}

/** Red at the bottom of the scale, amber in the middle, green at the top. */
function scoreColor(score: number, min: number, max: number): string {
    const position = max > min ? Math.min(1, Math.max(0, (score - min) / (max - min))) : 1
    return position < 0.5
        ? `color-mix(in oklab, var(--warning) ${Math.round(position * 200)}%, var(--danger))`
        : `color-mix(in oklab, var(--success) ${Math.round((position - 0.5) * 200)}%, var(--warning))`
}

export function ObservationHeadline({
    observation,
    onSeek,
}: {
    observation: ReplayObservationApi
    onSeek: (timestampMs: number) => void
}): JSX.Element | null {
    const snapshot = observation.scanner_snapshot
    const result = readResult(observation)
    if (!snapshot || !result) {
        return null
    }

    if (snapshot.scanner_type === 'monitor') {
        const verdict = typeof result.verdict === 'string' ? VERDICTS[result.verdict] : undefined
        return verdict ? (
            <span className={`self-start text-2xl ${PILL} ${verdict.className}`} data-attr="vision-observation-verdict">
                {verdict.label}
            </span>
        ) : (
            <span className="text-2xl font-bold text-muted">—</span>
        )
    }

    if (snapshot.scanner_type === 'scorer') {
        const score = typeof result.score === 'number' ? result.score : null
        const scale = (configFromSnapshot(snapshot) as ScorerScannerConfig | null)?.scale
        const min = typeof scale?.min === 'number' ? scale.min : 0
        const max = typeof scale?.max === 'number' ? scale.max : null
        const label = typeof result.label === 'string' ? result.label : (scale?.label ?? null)
        return (
            <div className="flex flex-col gap-1">
                <span className="text-3xl font-bold tabular-nums">
                    <span
                        // The color is a position on a continuous scale, which Tailwind classes can't express.
                        // eslint-disable-next-line react/forbid-dom-props
                        style={score !== null && max !== null ? { color: scoreColor(score, min, max) } : undefined}
                    >
                        {score ?? '—'}
                    </span>
                    {max !== null && <span className="text-lg font-normal text-muted"> / {max}</span>}
                </span>
                {label && <span className="text-sm text-secondary">{label}</span>}
            </div>
        )
    }

    if (snapshot.scanner_type === 'classifier') {
        const tags = Array.isArray(result.tags) ? (result.tags as string[]) : []
        const freeform = Array.isArray(result.tags_freeform) ? (result.tags_freeform as string[]) : []
        if (tags.length === 0 && freeform.length === 0) {
            return <span className="text-lg font-semibold text-muted">No categories</span>
        }
        return (
            <div className="flex flex-wrap gap-2">
                {tags.map((tag) => (
                    <span key={`tag-${tag}`} className={`text-lg ${PILL} text-accent border-accent`}>
                        {tag}
                    </span>
                ))}
                {freeform.map((tag) => (
                    <Tooltip
                        key={`freeform-${tag}`}
                        title="Freeform category: the model came up with this one because nothing in your list matched this part of the session."
                    >
                        <span className={`text-lg ${PILL} text-default border-primary cursor-help`}>
                            <IconSparkles className="text-base" />
                            {tag}
                        </span>
                    </Tooltip>
                ))}
            </div>
        )
    }

    if (snapshot.scanner_type === 'summarizer') {
        const title = typeof result.title === 'string' ? result.title : null
        const summary = typeof result.summary === 'string' ? result.summary : null
        return (
            <div className="flex flex-col gap-1">
                <div className="flex items-start justify-between gap-2">
                    {title && <span className="text-xl font-bold">{title}</span>}
                    {summary && (
                        <LemonButton
                            size="xsmall"
                            icon={<IconCopy />}
                            tooltip="Copy summary"
                            className="ml-auto"
                            onClick={() =>
                                void copyToClipboard(
                                    [title, citedTextToPlainText(summary, result.summary_segments)]
                                        .filter(Boolean)
                                        .join('\n\n'),
                                    'summary'
                                )
                            }
                            data-attr="vision-copy-summary"
                        />
                    )}
                </div>
                {summary && (
                    <span className="text-sm whitespace-pre-wrap">
                        <CitedText text={summary} segments={result.summary_segments} onSeek={onSeek} />
                    </span>
                )}
            </div>
        )
    }

    return <ObservationPrimaryOutput observation={observation} showPrompt={false} onSeek={onSeek} copyable />
}
