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
    insightShortId?: string | null
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
    compare_label?: 'current' | 'previous' | null
}

export interface StoryTrendsQuery {
    kind: 'TrendsQuery'
    interval?: string
    trendsFilter?: Record<string, unknown>
    series?: Record<string, unknown>[]
    [key: string]: unknown
}

export interface StoryFunnelsQuery {
    kind: 'FunnelsQuery'
    series?: Record<string, unknown>[]
    funnelsFilter?: Record<string, unknown>
    [key: string]: unknown
}

export interface StoryFunnelStep {
    name: string
    count: number
}

// What the explanation walks through, whichever insight drew it: a funnel over time is a time series too.
export type ExplainChartShape = 'time_series' | 'funnel_steps'

interface ExplainChartBase {
    /** The followed series on a trends chart, or the followed breakdown value on a funnel. */
    seriesIndex: number
    insightName: string | null
    headline: string
    chapters: StoryChapter[]
    warnings?: unknown[]
    _posthogUrl?: string
}

export interface TimeSeriesExplainChartData extends ExplainChartBase {
    shape: 'time_series'
    query: StoryTrendsQuery
    results: StorySeriesResult[]
    lastPointInProgress: boolean
}

export interface FunnelStepsExplainChartData extends ExplainChartBase {
    shape: 'funnel_steps'
    query: StoryFunnelsQuery
    /** The followed breakdown value's steps. A chapter's range indexes into them. */
    steps: StoryFunnelStep[]
    /** Every breakdown value's label, empty when the funnel has no breakdown. */
    breakdowns: string[]
}

export type ExplainChartData = TimeSeriesExplainChartData | FunnelStepsExplainChartData
