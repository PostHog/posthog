import { z } from 'zod'

const text = z.string().max(10000)
const id = z.string().min(1).max(128)
const cell = z.union([z.string().max(2000), z.number().finite(), z.boolean(), z.null()])

export const investigationEvidenceSchema = z.object({
    id,
    reference: z.number().int().positive(),
    title: z.string().max(200),
    kind: z.enum(['query', 'link']),
    sql: text,
    url: z.string().max(2000),
    note: text,
})

export const investigationHypothesisSchema = z.object({
    id,
    title: z.string().max(500),
    status: z.enum(['open', 'supported', 'ruled_out']),
    reasoning: text,
    evidenceIds: z.array(id).max(12),
})

export const investigationResultSchema = z.object({
    evidenceId: id,
    title: z.string().max(200),
    sql: text,
    columns: z.array(z.string().max(500)).max(20),
    rows: z.array(z.array(cell).max(20)).max(50),
    truncated: z.boolean(),
    error: z.string().max(2000).nullable(),
})

export const investigationRunSchema = z.object({
    id,
    at: z.string().datetime(),
    conclusion: text,
    results: z.array(investigationResultSchema).max(12),
})

export const investigationDocumentSchema = z.object({
    version: z.literal(1),
    question: z.string().max(500),
    status: z.enum(['investigating', 'review', 'monitoring', 'closed']),
    context: text,
    checks: z.array(z.enum(['definition', 'maturity', 'tracking', 'population'])).max(4),
    evidence: z.array(investigationEvidenceSchema).max(12),
    nextEvidenceNumber: z.number().int().positive(),
    hypotheses: z.array(investigationHypothesisSchema).max(12),
    conclusion: text,
    decision: text,
    followUp: z.string().max(2000),
    runs: z.array(investigationRunSchema).max(10),
    baselineId: id.nullable(),
    example: z.boolean(),
})

export interface InvestigationDocument extends z.infer<typeof investigationDocumentSchema> {}
export type InvestigationEvidence = z.infer<typeof investigationEvidenceSchema>
export type InvestigationHypothesis = z.infer<typeof investigationHypothesisSchema>
export type InvestigationRun = z.infer<typeof investigationRunSchema>
export type InvestigationResult = z.infer<typeof investigationResultSchema>

export const INVESTIGATION_CHECKS = {
    definition: 'Metric and conversion window are defined',
    maturity: 'Cohorts have had time to convert',
    tracking: 'Tracking and data freshness have been checked',
    population: 'Populations and comparison periods are comparable',
} as const

export function newInvestigation(question = ''): InvestigationDocument {
    return {
        version: 1,
        question,
        status: 'investigating',
        context: '',
        checks: [],
        evidence: [],
        nextEvidenceNumber: 1,
        hypotheses: [],
        conclusion: '',
        decision: '',
        followUp: '',
        runs: [],
        baselineId: null,
        example: false,
    }
}

export function appendInvestigationRun(document: InvestigationDocument, run: InvestigationRun): InvestigationDocument {
    const runs = [...document.runs, run]
    while (runs.length > 10) {
        const removable = runs.findIndex((item) => item.id !== document.baselineId)
        runs.splice(removable, 1)
    }
    return { ...document, runs }
}

export function removeInvestigationEvidence(
    document: InvestigationDocument,
    evidenceId: string
): InvestigationDocument {
    return {
        ...document,
        evidence: document.evidence.filter((item) => item.id !== evidenceId),
        hypotheses: document.hypotheses.map((item) => ({
            ...item,
            evidenceIds: item.evidenceIds.filter((reference) => reference !== evidenceId),
        })),
    }
}

export function getInvestigationLink(url: string): string | null {
    if (url.startsWith('/') && !url.startsWith('//') && !url.includes('\\')) {
        return url
    }
    try {
        const parsed = new URL(url)
        return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : null
    } catch {
        return null
    }
}

export function snapshotInvestigationResult(
    evidence: InvestigationEvidence,
    columns: string[],
    rows: unknown[][],
    hasMore = false
): InvestigationResult {
    let truncated = hasMore || rows.length > 50 || columns.length > 20
    const snapshotRows = rows.slice(0, 50).map((row) => {
        truncated ||= row.length > 20
        return row.slice(0, 20).map((value) => {
            if (value === null || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value))) {
                return value
            }
            const serialized = String(typeof value === 'object' ? JSON.stringify(value) : value)
            truncated ||= serialized.length > 2000
            return serialized.slice(0, 2000)
        })
    })
    truncated ||= columns.some((column) => column.length > 500)
    return {
        evidenceId: evidence.id,
        title: evidence.title,
        sql: evidence.sql,
        columns: columns.slice(0, 20).map((column) => column.slice(0, 500)),
        rows: snapshotRows,
        truncated,
        error: null,
    }
}

export type InvestigationComparison = {
    kind: 'new' | 'changed_query' | 'error' | 'unchanged' | 'changed' | 'incomplete'
    label: string
    delta: number | null
}

export function compareInvestigationResults(
    current: InvestigationResult,
    baseline?: InvestigationResult
): InvestigationComparison {
    if (current.error || baseline?.error) {
        return { kind: 'error', label: 'Query failed', delta: null }
    }
    if (!baseline) {
        return { kind: 'new', label: 'No baseline', delta: null }
    }
    if (current.sql !== baseline.sql || JSON.stringify(current.columns) !== JSON.stringify(baseline.columns)) {
        return { kind: 'changed_query', label: 'Definition changed', delta: null }
    }
    if (current.truncated || baseline.truncated) {
        return { kind: 'incomplete', label: 'Partial results', delta: null }
    }
    const same = JSON.stringify(current.rows) === JSON.stringify(baseline.rows)
    return {
        kind: same ? 'unchanged' : 'changed',
        label: same ? 'Unchanged' : 'Results changed',
        delta: investigationScalarDelta(current, baseline),
    }
}

function investigationScalarDelta(current: InvestigationResult, baseline: InvestigationResult): number | null {
    const currentValue = current.rows.length === 1 && current.columns.length === 1 ? current.rows[0][0] : null
    const baselineValue = baseline.rows.length === 1 && baseline.columns.length === 1 ? baseline.rows[0][0] : null
    return typeof currentValue === 'number' && typeof baselineValue === 'number' ? currentValue - baselineValue : null
}
