import { PostHogComDocsURL } from 'lib/lemon-ui/Link/Link'

import { QuerySchema } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

export const INITIAL_DATE_FROM = '-7d' as string
export const INITIAL_DATE_TO = null as string | null
export const INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED = false as boolean

export interface EmbeddedTileLayout {
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    colSpanClassName?: `md:col-span-${number}` | 'md:col-span-full'
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    rowSpanClassName?: `md:row-span-${number}`
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    orderWhenLargeClassName?: `xxl:order-${number}`
    className?: string
}

export enum EmbeddedAnalyticsTileId {
    API_QUERIES_COUNT = 'API_QUERIES_COUNT',
    API_READ_TB = 'API_READ_TB',
    API_CPU_SECONDS = 'API_CPU_SECONDS',
    API_QUERIES_PER_KEY = 'API_QUERIES_PER_KEY',
    API_LAST_20_QUERIES = 'API_LAST_20_QUERIES',
    API_EXPENSIVE_QUERIES = 'API_EXPENSIVE_QUERIES',
    API_FAILED_QUERIES = 'API_FAILED_QUERIES',
}

export const loadPriorityMap: Record<EmbeddedAnalyticsTileId, number> = {
    [EmbeddedAnalyticsTileId.API_QUERIES_COUNT]: 1,
    [EmbeddedAnalyticsTileId.API_READ_TB]: 2,
    [EmbeddedAnalyticsTileId.API_CPU_SECONDS]: 3,
    [EmbeddedAnalyticsTileId.API_QUERIES_PER_KEY]: 4,
    [EmbeddedAnalyticsTileId.API_LAST_20_QUERIES]: 5,
    [EmbeddedAnalyticsTileId.API_EXPENSIVE_QUERIES]: 6,
    [EmbeddedAnalyticsTileId.API_FAILED_QUERIES]: 7,
}

export interface EmbeddedBaseTile {
    tileId: EmbeddedAnalyticsTileId
    layout: EmbeddedTileLayout
    docs?: EmbeddedDocs
}

export interface EmbeddedDocs {
    url?: PostHogComDocsURL
    title: string
    description: string | JSX.Element
}

export interface UsageQueryTile extends EmbeddedBaseTile {
    kind: 'query'
    title?: string
    query: QuerySchema
    showIntervalSelect?: boolean
    control?: JSX.Element
    insightProps: InsightLogicProps
    canOpenModal?: boolean
    canOpenInsight?: boolean
}
