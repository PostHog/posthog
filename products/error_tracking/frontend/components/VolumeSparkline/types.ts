export type SparklineDatum = {
    date: Date
    value: number
    label?: string
    color?: string
    /** When true with `color`, bar uses diagonal stripe fill + animation */
    animated?: boolean
}

export type SparklineData = SparklineDatum[]

export type SparklineEvent<T = string> = {
    id: string
    date: Date
    payload: T
    radius?: number
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

export type SparklineOptions = {
    backgroundColor: string
    hoverBackgroundColor: string
    axisColor: string
    borderRadius: number
    eventLabelHeight: number
    eventMinSpace: number
    eventLabelPaddingX: number
    eventLabelPaddingY: number
    minBarHeight: number
}
