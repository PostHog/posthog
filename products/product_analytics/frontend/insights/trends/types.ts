import { ActionFilter, ActorType, FilterType, GraphDataset, TrendResult } from '~/types'

export interface TrendResponse {
    result: TrendResult[]
    filters: FilterType
    next?: string
}

export interface IndexedTrendResult extends TrendResult {
    /**
     * The index after applying visualization-specific sorting (e.g. for pie
     * chart) and filtering (e.g. for lifecycle toggles).
     */
    id: number
    /** The original index of the series, before re-sorting into visualization
     * specific order (e.g. for pie chart). The series index is used e.g. to
     * get series color correctly. */
    seriesIndex: number
    /** An index computed in trendsDataLogic that is used to generate colors. This index is the same for current and previous
     * series with the same label. The previous series is given a slightly lighter version of the same color.
     * */
    colorIndex: number
}

export interface TrendActors {
    seriesId?: number // The series identifier for this particular point (i.e. index of series)
    people: ActorType[]
    count: number
    missingPersons: number
    day: string | number
    label: string
    action?: ActionFilter
    breakdown_value?: string | number
    next?: string
    loadingMore?: boolean
    funnelStep?: number
    pathsDropoff?: boolean
    crossDataset?: GraphDataset[]
}
