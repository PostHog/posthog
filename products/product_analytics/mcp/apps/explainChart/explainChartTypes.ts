export type StoryConfidence = 'high' | 'medium' | 'low'

export interface StoryEvidenceChart {
    type: 'line' | 'bar'
    labels: string[]
    series: { name: string; values: number[] }[]
}

export interface StoryEvidence {
    text: string
    url: string | null
    query?: Record<string, unknown> | null
    chart?: StoryEvidenceChart | null
}

export interface StoryChapter {
    title: string
    /** Inclusive indexes into the series' points. Null when the chapter's dates match no point on the chart. */
    range: [number, number] | null
    summary: string | null
    cause: string | null
    confidence: StoryConfidence | null
    confidenceReason: string | null
    evidence: StoryEvidence[]
}

export interface StorySeriesResult {
    label?: string
    data?: number[]
    days?: string[]
    action?: { name?: string }
}

export interface StoryTrendsQuery {
    kind: 'TrendsQuery'
    interval?: string
    trendsFilter?: Record<string, unknown>
    series?: Record<string, unknown>[]
    [key: string]: unknown
}

export interface ExplainChartData {
    query: StoryTrendsQuery
    results: StorySeriesResult[]
    seriesIndex: number
    insightName: string | null
    lastPointInProgress: boolean
    headline: string
    chapters: StoryChapter[]
    warnings?: unknown[]
    _posthogUrl?: string
}
