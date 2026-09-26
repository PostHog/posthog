// A rate under this many observations is noise. Mirrors MIN_EVIDENCE_SAMPLE in
// products/workflows/backend/metrics.py.
export const MIN_EVIDENCE_SAMPLE = 20

// Mirrors EVIDENCE_UNITS in products/workflows/backend/api/hog_flow.py.
export type EvidenceUnit = 'rate' | 'count'

export interface GuardrailReading {
    metric: string
    value: number | null
    n?: number
    unit?: EvidenceUnit
}

export function readGuardrails(evidence: Record<string, unknown>): GuardrailReading[] {
    const raw = Array.isArray(evidence.guardrails) ? evidence.guardrails : []
    return raw.filter((entry): entry is GuardrailReading => !!entry && typeof entry === 'object' && 'metric' in entry)
}

export function readUnit(value: unknown): EvidenceUnit | null {
    return value === 'rate' || value === 'count' ? value : null
}

// The producer says what the number is. The unit is never guessed from the value's range, where
// a count of 1 would read as 100%.
export function formatValue(value: unknown, unit: EvidenceUnit | null): string | null {
    if (typeof value !== 'number') {
        return null
    }
    return unit === 'rate' ? `${(value * 100).toFixed(1)}%` : String(value)
}

export interface MeasuredReading {
    metric: string
    value: number | null
    n: number
    below_minimum_sample: boolean
}

/** PostHog's own read of the step at `base_version`, stored by the server when the suggestion was filed. */
export interface MeasuredEvidence {
    version: number
    window: string
    target: MeasuredReading
    click_through: MeasuredReading
    guardrails: MeasuredReading[]
}

export function readMeasured(evidence: Record<string, unknown>): MeasuredEvidence | null {
    const measured = evidence.measured
    if (!measured || typeof measured !== 'object' || !('target' in measured)) {
        return null
    }
    return measured as MeasuredEvidence
}

export function describeWindow(window: string): string {
    const match = /^-(\d+)([dh])$/.exec(window)
    if (!match) {
        return window
    }
    const unit = match[2] === 'd' ? 'day' : 'hour'
    return `the last ${match[1]} ${unit}${match[1] === '1' ? '' : 's'}`
}

// Half a point: the producer reads the same series moments earlier.
const RATE_TOLERANCE = 0.005

export function evidenceDisagrees(evidence: Record<string, unknown>, measured: MeasuredEvidence): boolean {
    if (
        readUnit(evidence.unit) !== 'rate' ||
        typeof evidence.current_value !== 'number' ||
        measured.target.value === null
    ) {
        return false
    }
    if (typeof evidence.n === 'number' && evidence.n !== measured.target.n) {
        return true
    }
    return Math.abs(evidence.current_value - measured.target.value) > RATE_TOLERANCE
}
