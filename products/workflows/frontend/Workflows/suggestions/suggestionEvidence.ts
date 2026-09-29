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
