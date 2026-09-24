import { IconSparkles } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LabeledRow } from '../components/LabeledRow'
import { ObservationPrimaryOutput } from '../components/ObservationCard'
import type { ReplayObservationApi, ScannerTypeEnumApi } from '../generated/api.schemas'
import { configFromSnapshot, type ScorerScannerConfig } from '../replay_scanners/types'
import {
    type MonitorVerdict,
    VERDICT_LABEL,
    readFixedTags,
    readFreeformTags,
    readModelOutput,
    readScore,
    readVerdict,
} from '../utils/observation'

const PILL = 'inline-flex items-center gap-1 rounded-md border-2 px-3 py-0.5 font-bold'

// Only the chosen categories show here, so the classifier's label names them as assigned.
const HEADLINE_LABEL: Record<ScannerTypeEnumApi, string> = {
    monitor: 'Verdict',
    scorer: 'Score',
    classifier: 'Assigned categories',
    summarizer: 'Summary',
}

const VERDICT_CLASS: Record<MonitorVerdict, string> = {
    yes: 'text-success border-success',
    no: 'text-danger border-danger',
    inconclusive: 'text-muted border-primary',
}

/** Red at the bottom of the scale, amber in the middle, green at the top. */
function scoreColor(score: number, min: number, max: number): string {
    const position = max > min ? Math.min(1, Math.max(0, (score - min) / (max - min))) : 1
    return position < 0.5
        ? `color-mix(in oklab, var(--warning) ${Math.round(position * 200)}%, var(--danger))`
        : `color-mix(in oklab, var(--success) ${Math.round((position - 0.5) * 200)}%, var(--warning))`
}

function HeadlineValue({
    observation,
    scannerType,
    onSeek,
}: {
    observation: ReplayObservationApi
    scannerType: ScannerTypeEnumApi
    onSeek: (timestampMs: number) => void
}): JSX.Element {
    if (scannerType === 'monitor') {
        const verdict = readVerdict(observation)
        return verdict ? (
            <span
                className={`self-start text-2xl ${PILL} ${VERDICT_CLASS[verdict]}`}
                data-attr="vision-observation-verdict"
            >
                {VERDICT_LABEL[verdict]}
            </span>
        ) : (
            <span className="text-2xl font-bold text-muted">—</span>
        )
    }

    if (scannerType === 'scorer') {
        const score = readScore(observation)
        const scale = (configFromSnapshot(observation.scanner_snapshot) as ScorerScannerConfig | null)?.scale
        const min = typeof scale?.min === 'number' ? scale.min : 0
        const max = typeof scale?.max === 'number' ? scale.max : null
        const resultLabel = readModelOutput(observation)?.label
        const label = typeof resultLabel === 'string' ? resultLabel : (scale?.label ?? null)
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

    if (scannerType === 'classifier') {
        const tags = readFixedTags(observation)
        const freeform = readFreeformTags(observation)
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

    return (
        <ObservationPrimaryOutput
            observation={observation}
            showPrompt={false}
            onSeek={onSeek}
            expandSummary
            copyable
            largeTitle
        />
    )
}

export function ObservationHeadline({
    observation,
    onSeek,
}: {
    observation: ReplayObservationApi
    onSeek: (timestampMs: number) => void
}): JSX.Element | null {
    const scannerType = observation.scanner_snapshot?.scanner_type
    if (!scannerType || !readModelOutput(observation)) {
        return null
    }
    return (
        <LabeledRow label={HEADLINE_LABEL[scannerType] ?? 'Result'}>
            <HeadlineValue observation={observation} scannerType={scannerType} onSeek={onSeek} />
        </LabeledRow>
    )
}
