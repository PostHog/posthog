import { DateDisplay } from 'lib/components/DateDisplay'
import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter } from 'lib/utils'
import { hasBreakdown } from 'scenes/funnels/funnelUtils'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import type { OpenPersonsModalProps } from 'scenes/trends/persons-modal/PersonsModal'

import type { Noun } from '~/models/groupsModel'
import type { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import {
    type BreakdownFilter,
    type FunnelsActorsQuery,
    type FunnelsQuery,
    NodeKind,
    type ResolvedDateRangeResponse,
} from '~/queries/schema/schema-general'
import type { CohortType, IntervalType } from '~/types'

import type { FunnelSeriesMeta } from '../shared/funnelSeriesMeta'

export interface FunnelLineChartClickDeps {
    hasPersonsModal: boolean
    querySource: FunnelsQuery | null | undefined
    interval: IntervalType | null | undefined
    timezone?: string
    weekStartDay: number | null | undefined
    resolvedDateRange: ResolvedDateRangeResponse | null | undefined
    breakdownFilter: BreakdownFilter | null | undefined
    aggregationTargetLabel: Noun
    cohorts: CohortType[]
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined
    openPersonsModal: (props: OpenPersonsModalProps) => void
}

export function handleFunnelLineChartClick(
    meta: FunnelSeriesMeta,
    dataIndex: number,
    deps: FunnelLineChartClickDeps
): void {
    if (!deps.hasPersonsModal || !deps.querySource) {
        return
    }

    const day = meta.days?.[dataIndex]
    if (day == null || day === '') {
        return
    }

    const breakdownValue = meta.breakdown_value
    const breakdownLabel = hasBreakdown(breakdownValue)
        ? formatBreakdownLabel(
              breakdownValue,
              deps.breakdownFilter ?? null,
              deps.cohorts,
              deps.formatPropertyValueForDisplay
          )
        : null

    const title = (
        <>
            {capitalizeFirstLetter(deps.aggregationTargetLabel.plural)} converted on{' '}
            <DateDisplay
                interval={deps.interval || 'day'}
                resolvedDateRange={deps.resolvedDateRange ?? undefined}
                timezone={deps.timezone}
                weekStartDay={deps.weekStartDay ?? undefined}
                date={day.toString()}
            />
            {breakdownLabel ? <> • {breakdownLabel}</> : null}
        </>
    )

    const query: FunnelsActorsQuery = {
        kind: NodeKind.FunnelsActorsQuery,
        source: deps.querySource,
        funnelTrendsDropOff: false,
        includeRecordings: true,
        funnelTrendsEntrancePeriodStart: dayjs(day).format('YYYY-MM-DD HH:mm:ss'),
        ...(hasBreakdown(breakdownValue) ? { funnelStepBreakdown: breakdownValue } : {}),
    }
    deps.openPersonsModal({ title, query })
}
