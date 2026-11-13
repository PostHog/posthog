import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { DateDisplay } from 'lib/components/DateDisplay'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { dayjs } from 'lib/dayjs'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownKeyType, FunnelStepWithConversionMetrics } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { hasBreakdown } from '../funnelUtils'
import { ValueInspectorButton } from '../shared/ValueInspectorButton'
import { buildFunnelTrendsActorsQuery } from './funnelTrendsTableUtils'
import { QuillFunnelTrendsTable } from './QuillFunnelTrendsTable'

/** Runtime shape of a `funnelDataLogic.indexedSteps` row when the funnel is in trends mode. */
export type FunnelTrendSeries = {
    id: number
    colorIndex: number
    data: number[]
    days: string[]
    labels: string[]
    breakdown_value?: BreakdownKeyType
    compare?: boolean
    compare_label?: 'current' | 'previous'
}

export interface FunnelTrendsPeriod {
    date: string
    secondaryDate?: string
    isInProgress: boolean
}

function unwrapBreakdownValue(breakdownValue: BreakdownKeyType | undefined): BreakdownKeyType | undefined {
    return Array.isArray(breakdownValue) && breakdownValue.length === 1 ? breakdownValue[0] : breakdownValue
}

export function FunnelTrendsTable(): JSX.Element | null {
    const { insightProps, insightLoading } = useValues(insightLogic)
    const {
        indexedSteps,
        incompletenessOffsetFromEnd,
        breakdownFilter,
        aggregationTargetLabel,
        getFunnelsColor,
        querySource,
        insightData,
        interval,
    } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { weekStartDay, timezone } = useValues(teamLogic)
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const quillSurface = useQuillSurface()

    const seriesRows = indexedSteps as unknown as FunnelTrendSeries[]

    if (!seriesRows || seriesRows.length === 0 || !seriesRows[0]?.data) {
        return null
    }

    const periodCount = seriesRows[0].data.length
    const currentSeries = seriesRows.find((row) => row.compare_label !== 'previous') ?? seriesRows[0]
    const previousSeries = seriesRows.find((row) => row.compare_label === 'previous')

    const seriesLabel = (row: FunnelTrendSeries): string =>
        hasBreakdown(row.breakdown_value)
            ? formatBreakdownLabel(
                  unwrapBreakdownValue(row.breakdown_value),
                  breakdownFilter,
                  allCohorts.results,
                  formatPropertyValueForDisplay
              )
            : 'Conversion'

    const openModalForCell = (row: FunnelTrendSeries, index: number): void => {
        const day = row.days?.[index] ?? ''
        const breakdownValue = row.breakdown_value
        // No breakdown value in the title: the modal's breakdown dropdown communicates (and can
        // change) the selected value, so a static title would go stale.
        const title = (
            <>
                {capitalizeFirstLetter(aggregationTargetLabel.plural)} converted on{' '}
                <DateDisplay
                    interval={interval || 'day'}
                    resolvedDateRange={insightData?.resolved_date_range}
                    timezone={timezone}
                    weekStartDay={weekStartDay}
                    date={day.toString()}
                />
            </>
        )
        const query = buildFunnelTrendsActorsQuery({
            source: querySource!,
            entrancePeriodStart: dayjs(day).format('YYYY-MM-DD HH:mm:ss'),
            breakdownValue,
            compare: row.compare_label,
        })
        openPersonsModal({ title, query })
    }

    const periods = Array.from(
        { length: periodCount },
        (_, index): FunnelTrendsPeriod => ({
            date: (currentSeries.days || currentSeries.labels)[index],
            secondaryDate: previousSeries ? (previousSeries.days || previousSeries.labels)[index] : undefined,
            isInProgress: index >= periodCount + incompletenessOffsetFromEnd,
        })
    )

    // getFunnelsColor positions colors by `order`, which trend rows don't carry. Feed
    // colorIndex into that slot so each series gets the same color as its line in the chart.
    const rowColor = (row: FunnelTrendSeries): string =>
        getFunnelsColor({ ...row, order: row.colorIndex } as unknown as FunnelStepWithConversionMetrics)

    if (quillSurface) {
        return (
            <QuillFunnelTrendsTable
                rows={seriesRows}
                periods={periods}
                loading={insightLoading}
                seriesLabel={seriesLabel}
                rowColor={rowColor}
                onOpenPersons={canOpenPersonModal ? openModalForCell : undefined}
            />
        )
    }

    const periodColumns = periods.map(
        (period, index): LemonTableColumn<FunnelTrendSeries, keyof FunnelTrendSeries | undefined> => ({
            key: `period_${index}`,
            align: 'right',
            title: (
                <DateDisplay
                    interval={interval || 'day'}
                    resolvedDateRange={insightData?.resolved_date_range}
                    timezone={timezone}
                    weekStartDay={weekStartDay}
                    date={period.date}
                    secondaryDate={period.secondaryDate}
                    hideWeekRange
                />
            ),
            render: (_, row) => {
                const value = `${humanFriendlyNumber(row.data[index] ?? 0, 1)}%`
                const cell = canOpenPersonModal ? (
                    <ValueInspectorButton onClick={() => openModalForCell(row, index)}>{value}</ValueInspectorButton>
                ) : (
                    value
                )
                return period.isInProgress ? (
                    <Tooltip title="This period is still in progress">
                        <span className="text-secondary">{cell}</span>
                    </Tooltip>
                ) : (
                    cell
                )
            },
        })
    )

    const columns: LemonTableColumns<FunnelTrendSeries> = [
        {
            title: 'Series',
            key: 'series',
            render: (_, row) => (
                <span className="font-medium inline-flex items-center gap-2">
                    {seriesLabel(row)}
                    {row.compare_label && <LemonTag>{capitalizeFirstLetter(row.compare_label)}</LemonTag>}
                </span>
            ),
        },
        ...periodColumns,
    ]

    return (
        <LemonTable
            dataSource={seriesRows}
            columns={columns}
            loading={insightLoading}
            rowKey="id"
            data-attr="funnel-trends-table"
            firstColumnSticky
            rowRibbonColor={rowColor}
        />
    )
}
