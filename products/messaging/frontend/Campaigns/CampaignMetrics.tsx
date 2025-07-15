import { IconCalendar } from '@posthog/icons'
import { LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import { useEffect } from 'react'

import { campaignMetricsLogic, CampaignMetricsLogicProps } from './campaignMetricsLogic'

export function CampaignMetrics({ id }: CampaignMetricsLogicProps): JSX.Element {
    // Get the metrics based off of the campaign id
    const { loadMetricsByKind } = useActions(campaignMetricsLogic({ id }))

    useEffect(() => {
        loadMetricsByKind()
    }, [id])

    return (
        <BindLogic logic={campaignMetricsLogic} props={{ id }}>
            <div className="flex flex-col gap-2">
                <CampaignMetricsFilters />
                <CampaignMetricsTotals />
            </div>
        </BindLogic>
    )
}

function CampaignMetricsFilters(): JSX.Element {
    const { filters } = useValues(campaignMetricsLogic)
    const { setFilters } = useActions(campaignMetricsLogic)

    return (
        <div className="flex gap-2 items-center">
            <LemonSelect
                options={[
                    { label: 'Hourly', value: 'hour' },
                    { label: 'Daily', value: 'day' },
                    { label: 'Weekly', value: 'week' },
                ]}
                size="small"
                value={filters.interval}
                onChange={(value) => setFilters({ interval: value })}
            />
            <DateFilter
                dateTo={filters.before}
                dateFrom={filters.after}
                onChange={(from, to) => setFilters({ after: from || undefined, before: to || undefined })}
                allowedRollingDateOptions={['days', 'weeks', 'months', 'years']}
                makeLabel={(key) => (
                    <>
                        <IconCalendar /> {key}
                    </>
                )}
            />
        </div>
    )
}

const METRICS_INFO = {
    succeeded: 'Total number of events processed successfully',
    failed: 'Total number of events that had errors during processing',
    filtered: 'Total number of events that were filtered out',
    filtering_failed: 'Total number of events that failed to be filtered',
    disabled_temporarily:
        'Total number of events that were skipped due to the destination being temporarily disabled (due to issues such as the destination being down or rate-limited)',
    disabled_permanently:
        'Total number of events that were skipped due to the destination being permanently disabled (due to prolonged issues with the destination)',
}

function CampaignMetric({
    label,
    value,
    tooltip,
}: {
    label: string
    value: number | undefined
    tooltip: JSX.Element | string
}): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            <div className="flex flex-col flex-1 gap-2 items-center p-2 rounded border bg-surface-primary">
                <div className="text-xs font-bold uppercase">{label.replace(/_/g, ' ')}</div>
                <div className="flex flex-1 items-center mb-2 text-2xl">{humanFriendlyNumber(value ?? 0)}</div>
            </div>
        </Tooltip>
    )
}

function CampaignMetricsTotals(): JSX.Element {
    const { metricsByKind, metricsByKindLoading } = useValues(campaignMetricsLogic)

    return (
        <div className="flex flex-wrap gap-2 items-center">
            {Object.entries(METRICS_INFO).map(([key, value]) => (
                <div key={key} className="flex flex-col flex-1 h-30 min-w-30 max-w-100">
                    {metricsByKindLoading ? (
                        <LemonSkeleton className="w-full h-full" />
                    ) : (
                        <CampaignMetric label={key} value={metricsByKind?.[key]?.total} tooltip={value} />
                    )}
                </div>
            ))}
        </div>
    )
}
