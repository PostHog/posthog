export type StoryConfidence = 'high' | 'medium' | 'low'

export interface StoryEvidenceChartData {
    type: 'line' | 'bar'
    labels: string[]
    /** The axis label of each point, which leaves out a date that repeats. */
    ticks?: string[]
    /** Null where a breakdown value has no row for that point. */
    series: { name: string; values: (number | null)[] }[]
    yAxisLabel: string | null
}

export interface StoryEvidence {
    text: string
    url: string | null
    query?: Record<string, unknown> | null
    queryTool?: string | null
    chart?: StoryEvidenceChartData | null
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
