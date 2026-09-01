// A rate under this many observations is noise. Mirrors MIN_EVIDENCE_SAMPLE in
// products/workflows/backend/metrics.py.
export const MIN_EVIDENCE_SAMPLE = 20

export interface GuardrailReading {
    metric: string
    value: number | null
    n?: number
}

export function readGuardrails(evidence: Record<string, unknown>): GuardrailReading[] {
    const raw = Array.isArray(evidence.guardrails) ? evidence.guardrails : []
    return raw.filter((entry): entry is GuardrailReading => !!entry && typeof entry === 'object' && 'metric' in entry)
}

export function formatValue(value: unknown): string | null {
    if (typeof value !== 'number') {
        return null
    }
    return value > 0 && value <= 1 ? `${(value * 100).toFixed(1)}%` : String(value)
}
