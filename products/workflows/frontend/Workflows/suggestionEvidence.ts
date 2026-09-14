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

// The producer says what the number is. Guessing from the range reads a count of 1 as 100%, and a
// suggestion older than the `unit` contract has no unit to read, so it shows the number as it is.
export function formatValue(value: unknown, unit: EvidenceUnit | null): string | null {
    if (typeof value !== 'number') {
        return null
    }
    return unit === 'rate' ? `${(value * 100).toFixed(1)}%` : String(value)
}
