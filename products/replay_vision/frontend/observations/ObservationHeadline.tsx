import { IconCheckCircle, IconQuestion, IconSparkles, IconXCircle } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LabeledRow } from '../components/LabeledRow'
import { ObservationPrimaryOutput } from '../components/ObservationCard'
import type { PromptValenceEnumApi, ReplayObservationApi, ScannerTypeEnumApi } from '../generated/api.schemas'
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

// The `--success`/`--danger` family LemonTag uses. The `text-success` utility maps to a different, brighter green.
const GOOD_CLASS = 'text-success-dark dark:text-success-light'
const BAD_CLASS = 'text-danger-dark dark:text-danger-light'

const VERDICT_ICON: Record<MonitorVerdict, typeof IconCheckCircle> = {
    yes: IconCheckCircle,
    no: IconXCircle,
    inconclusive: IconQuestion,
}

function verdictClass(verdict: MonitorVerdict, valence: PromptValenceEnumApi | null): string {
    if (verdict === 'inconclusive') {
        return 'text-secondary dark:text-default'
    }
    if (valence !== 'good' && valence !== 'bad') {
        return 'text-default'
    }
    return (verdict === 'yes') === (valence === 'good') ? GOOD_CLASS : BAD_CLASS
}

function scorerScale(observation: ReplayObservationApi): { min: number; max: number | null; label: string | null } {
    const scale = (configFromSnapshot(observation.scanner_snapshot) as ScorerScannerConfig | null)?.scale
    return {
        min: typeof scale?.min === 'number' ? scale.min : 0,
        max: typeof scale?.max === 'number' ? scale.max : null,
        label: scale?.label ?? null,
    }
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

/** Red at the bad end of the scale through amber to green at the good end, null when its direction is unknown. */
function scoreColor(score: number, min: number, max: number, valence: PromptValenceEnumApi | null): string | null {
    if (valence !== 'good' && valence !== 'bad') {
        return null
    }
    const fromMin = max > min ? Math.min(1, Math.max(0, (score - min) / (max - min))) : 1
    const position = valence === 'good' ? fromMin : 1 - fromMin
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
        if (!verdict) {
            return <span className="text-xl font-bold text-muted">—</span>
        }
        const Icon = VERDICT_ICON[verdict]
        return (
            <span
                className={`inline-flex items-center gap-1.5 text-xl font-bold ${verdictClass(verdict, observation.prompt_valence)}`}
                data-attr="vision-observation-verdict"
            >
                <Icon className="text-2xl" />
                {VERDICT_LABEL[verdict]}
            </span>
        )
    }

    if (scannerType === 'scorer') {
        const score = readScore(observation)
        const { min, max } = scorerScale(observation)
        const color = score !== null && max !== null ? scoreColor(score, min, max, observation.prompt_valence) : null
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
