export type SparklineDatum = {
    date: Date
    value: number
    color?: string
    /** With `color`, flags the bar as a detected spike: its own color plus animated stripes. */
    isSpike?: boolean
}

export type SparklineData = SparklineDatum[]

export type SparklineEvent<T = string> = {
    id: string
    date: Date
    payload: T
    color?: string
}

export type VolumeSparklineLayout = 'compact' | 'detailed'

export type VolumeSparklineXAxisMode = 'none' | 'minimal' | 'full'

export type VolumeSparklineHoverSelection =
    | { kind: 'bin'; index: number; datum: SparklineDatum }
    | { kind: 'event'; event: SparklineEvent<string> }

export type ErrorTrackingVolumeSparklineHoverValues = {
    hoveredIndex: number | null
    hoveredDatum: SparklineDatum | null
    isBarHighlighted: boolean
    hoverSelection: VolumeSparklineHoverSelection | null
}
