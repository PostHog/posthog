import { PostHogComDocsURL } from 'lib/lemon-ui/Link/Link'

import { QuerySchema } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

export const INITIAL_DATE_FROM = '-7d' as string
export const INITIAL_DATE_TO = null as string | null
export const INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED = false as boolean

export interface EndpointsUsageTileLayout {
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    colSpanClassName?: `md:col-span-${number}` | 'md:col-span-full'
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    rowSpanClassName?: `md:row-span-${number}`
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    orderWhenLargeClassName?: `xxl:order-${number}`
    className?: string
}

export enum EndpointsUsageTileId {
    API_QUERIES_COUNT = 'API_QUERIES_COUNT',
    API_READ_TB = 'API_READ_TB',
    API_CPU_SECONDS = 'API_CPU_SECONDS',
    API_QUERIES_PER_KEY = 'API_QUERIES_PER_KEY',
    API_LAST_20_QUERIES = 'API_LAST_20_QUERIES',
    API_EXPENSIVE_QUERIES = 'API_EXPENSIVE_QUERIES',
    API_FAILED_QUERIES = 'API_FAILED_QUERIES',
}

export const loadPriorityMap: Record<EndpointsUsageTileId, number> = {
    [EndpointsUsageTileId.API_QUERIES_COUNT]: 1,
    [EndpointsUsageTileId.API_READ_TB]: 2,
    [EndpointsUsageTileId.API_CPU_SECONDS]: 3,
    [EndpointsUsageTileId.API_QUERIES_PER_KEY]: 4,
    [EndpointsUsageTileId.API_LAST_20_QUERIES]: 5,
    [EndpointsUsageTileId.API_EXPENSIVE_QUERIES]: 6,
    [EndpointsUsageTileId.API_FAILED_QUERIES]: 7,
}

export interface EndpointsUsageBaseTile {
    tileId: EndpointsUsageTileId
    layout: EndpointsUsageTileLayout
    docs?: EndpointsDocs
}

export interface EndpointsDocs {
    url?: PostHogComDocsURL
    title: string
    description: string | JSX.Element
}

export interface EndpointsUsageQueryTile extends EndpointsUsageBaseTile {
    kind: 'query'
    title?: string
    query: QuerySchema
    showIntervalSelect?: boolean
    control?: JSX.Element
    insightProps: InsightLogicProps
    canOpenModal?: boolean
    canOpenInsight?: boolean
}
