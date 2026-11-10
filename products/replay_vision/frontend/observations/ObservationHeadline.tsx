import { IconSparkles } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LabeledRow } from '../components/LabeledRow'
import { ObservationPrimaryOutput } from '../components/ObservationCard'
import type { ReplayObservationApi, ScannerTypeEnumApi } from '../generated/api.schemas'
import {
    VERDICT_LABEL,
    readFixedTags,
    readFreeformTags,
    readModelOutput,
    readScore,
    readVerdict,
} from '../utils/observation'
import { VERDICT_ICON, scoreColorFor, scorerScale, verdictClassFor } from '../utils/resultValence'
import { ConfidenceBadge } from './ConfidenceBadge'

// Filled, so each category stays visible in dark mode, where a tag's outline alone fades into the card.
const CATEGORY_CLASS =
    'inline-flex items-center gap-1 rounded-md border-[1.5px] border-primary bg-surface-secondary px-2.5 py-0.5 text-sm font-semibold text-default'

// Only the chosen categories show here, so the classifier's label names them as assigned.
const HEADLINE_LABEL: Record<ScannerTypeEnumApi, string> = {
    monitor: 'Verdict',
    scorer: 'Score',
    classifier: 'Assigned categories',
    summarizer: 'Summary',
    experiment: 'Summary',
}

/** The scale's name, stamped on each result from the scanner config. Older results may lack it. */
function scoreLabel(observation: ReplayObservationApi): string | null {
    const resultLabel = readModelOutput(observation)?.label
    return typeof resultLabel === 'string' && resultLabel ? resultLabel : scorerScale(observation).label
}

// A few teams write a sentence as the scale name, which would push the confidence badge off the heading line.
const MAX_SCALE_LABEL_CHARS = 40

function headlineLabel(observation: ReplayObservationApi, scannerType: ScannerTypeEnumApi): string {
    const label = HEADLINE_LABEL[scannerType] ?? 'Result'
    // The scale's name says what is scored, so it sits with the heading rather than beside the number.
    const scale = scannerType === 'scorer' ? scoreLabel(observation)?.trim() : null
    if (!scale) {
        return label
    }
    // Most teams type the name in lowercase, and headings are in sentence case.
    const name = scale.charAt(0).toUpperCase() + scale.slice(1)
    const shown = name.length > MAX_SCALE_LABEL_CHARS ? `${name.slice(0, MAX_SCALE_LABEL_CHARS - 1).trimEnd()}…` : name
    return `${label} · ${shown}`
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
        if (!verdict) {
            return <span className="text-xl font-bold text-muted">—</span>
        }
        const Icon = VERDICT_ICON[verdict]
        return (
            <span
                className={`inline-flex items-center gap-1.5 text-xl font-bold ${verdictClassFor(observation, verdict)}`}
                data-attr="vision-observation-verdict"
            >
                <Icon className="text-2xl" />
                {VERDICT_LABEL[verdict]}
            </span>
        )
    }

    if (scannerType === 'scorer') {
        const score = readScore(observation)
        const { max } = scorerScale(observation)
        const color = score !== null ? scoreColorFor(observation, score) : null
        return (
            <span className="text-3xl font-bold tabular-nums">
                <span
                    // The color is a position on a continuous scale, which Tailwind classes can't express.
                    // eslint-disable-next-line react/forbid-dom-props
                    style={color ? { color } : undefined}
                >
                    {score ?? '—'}
                </span>
                {max !== null && <span className="text-lg font-normal text-muted"> / {max}</span>}
            </span>
        )
    }

    if (scannerType === 'classifier') {
        const tags = readFixedTags(observation)
        const freeform = readFreeformTags(observation)
        if (tags.length === 0 && freeform.length === 0) {
            return <span className="text-lg font-semibold text-muted">No categories</span>
        }
        return (
            <div className="flex flex-wrap items-center gap-1.5">
                {tags.map((tag) => (
                    <span key={`tag-${tag}`} className={CATEGORY_CLASS}>
                        {tag}
                    </span>
                ))}
                {freeform.map((tag) => (
                    <Tooltip
                        key={`freeform-${tag}`}
                        title="Freeform category: the model came up with this one because nothing in your list matched this part of the session."
                    >
                        <span className={`${CATEGORY_CLASS} cursor-help`}>
                            <IconSparkles className="text-sm" />
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
    hideLabel = false,
}: {
    observation: ReplayObservationApi
    onSeek: (timestampMs: number) => void
    /** For when a tab around the headline already names it. */
    hideLabel?: boolean
}): JSX.Element | null {
    const scannerType = observation.scanner_snapshot?.scanner_type
    if (!scannerType || !readModelOutput(observation)) {
        return null
    }
    if (hideLabel) {
        return <HeadlineValue observation={observation} scannerType={scannerType} onSeek={onSeek} />
    }
    return (
        // The badge sits on the heading's line, so it has the same place for every scanner type.
        <LabeledRow
            label={headlineLabel(observation, scannerType)}
            size="medium"
            aside={<ConfidenceBadge observation={observation} />}
        >
            <HeadlineValue observation={observation} scannerType={scannerType} onSeek={onSeek} />
        </LabeledRow>
    )
}
