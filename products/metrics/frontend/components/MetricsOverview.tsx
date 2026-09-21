import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { _MetricsOverviewServiceApi } from '../generated/api.schemas'
import { STALE_AFTER_MS, metricsOverviewLogic } from './metricsOverviewLogic'

const isStale = (lastSeen: string): boolean => dayjs().diff(dayjs(lastSeen)) > STALE_AFTER_MS

// Shared by the loaded cards and their placeholders, so a rename cannot make the
// labels change as the data lands.
const STAT_LABELS = ['Services', 'Metric names', 'Active series'] as const

// Header text only, so the placeholder table has the same columns as the real one.
const SERVICE_COLUMN_TITLES = ['Service', 'Metrics', 'Active series', 'Last seen']

// `null` renders the placeholder. One component for both states, so the loading
// card cannot drift from the loaded one and change size when the data lands.
const OverviewStat = ({
    label,
    value,
    caption,
}: {
    label: string
    value: number | null
    caption: string | null
}): JSX.Element => (
    <div className="flex flex-col border rounded p-4 flex-1 min-w-40">
        {value === null ? (
            <LemonSkeleton className="h-8 w-20" />
        ) : (
            <span className="text-2xl font-semibold">{humanFriendlyNumber(value)}</span>
        )}
        <span className="text-sm">{label}</span>
        {caption === null ? (
            <LemonSkeleton className="h-3 w-24 my-1" />
        ) : (
            <span className="text-xs text-secondary">{caption}</span>
        )}
    </div>
)

// The window length arrives with the data, so the captions are placeholders too
// rather than a hardcoded guess that flashes if the server default ever changes.
const MetricsOverviewSkeleton = (): JSX.Element => (
    <div className="flex flex-col gap-4">
        <LemonSkeleton className="h-8 w-80" />
        <div className="flex flex-wrap gap-2">
            {STAT_LABELS.map((label) => (
                <OverviewStat key={label} label={label} value={null} caption={null} />
            ))}
        </div>
        <LemonTable
            dataSource={[]}
            loading
            rowKey="service_name"
            columns={SERVICE_COLUMN_TITLES.map((title) => ({
                title,
                align: title === 'Metrics' || title === 'Active series' ? 'right' : undefined,
            }))}
        />
    </div>
)

const IngestionStatus = ({ lastSeen }: { lastSeen: string | null }): JSX.Element => {
    if (lastSeen === null) {
        return (
            <LemonBanner
                type="info"
                action={{ to: 'https://posthog.com/docs/metrics', targetBlank: true, children: 'Setup guide' }}
            >
                No metrics have arrived yet. Follow the setup guide to start sending them.
            </LemonBanner>
        )
    }

    if (isStale(lastSeen)) {
        return (
            <LemonBanner
                type="warning"
                action={{
                    to: 'https://posthog.com/docs/metrics',
                    targetBlank: true,
                    children: 'Troubleshoot setup',
                }}
            >
                No metrics received in the last 15 minutes. The last datapoint arrived <TZLabel time={lastSeen} />.
                Check that your exporters and agents are still running.
            </LemonBanner>
        )
    }

    return (
        <div className="flex items-center gap-2 px-3 py-1.5 border border-accent rounded self-start">
            <div className="relative flex items-center justify-center">
                <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                <div className="w-2 h-2 bg-accent rounded-full" />
            </div>
            <span className="text-sm">
                Receiving metrics. Last datapoint <TZLabel time={lastSeen} />.
            </span>
        </div>
    )
}

export const MetricsOverview = (): JSX.Element => {
    const { overview, overviewLoading } = useValues(metricsOverviewLogic)
    const { viewService } = useActions(metricsOverviewLogic)

    if (!overview) {
        return <MetricsOverviewSkeleton />
    }

    const windowHours = Math.round(overview.lookback_seconds / 3600)
    const windowLabel = `Last ${windowHours} hours`

    return (
        <div className="flex flex-col gap-4">
            <IngestionStatus lastSeen={overview.last_seen} />
            <div className="flex flex-wrap gap-2">
                {STAT_LABELS.map((label) => (
                    <OverviewStat
                        key={label}
                        label={label}
                        value={
                            {
                                Services: overview.services.length,
                                'Metric names': overview.metric_names,
                                'Active series': overview.series,
                            }[label]
                        }
                        caption={windowLabel}
                    />
                ))}
            </div>
            <LemonTable
                dataSource={overview.services as _MetricsOverviewServiceApi[]}
                loading={overviewLoading && overview.services.length === 0}
                rowKey="service_name"
                emptyState={`No services have reported metrics in the ${windowLabel.toLowerCase()}.`}
                columns={[
                    {
                        title: 'Service',
                        key: 'service_name',
                        render: (_, service) => (
                            <Link
                                data-attr="metrics-overview-service-link"
                                title="View this service's metrics in the viewer"
                                onClick={() => viewService(service.service_name)}
                            >
                                {service.service_name || 'unknown'}
                            </Link>
                        ),
                    },
                    {
                        title: 'Metrics',
                        key: 'metric_names',
                        align: 'right',
                        render: (_, service) => humanFriendlyNumber(service.metric_names),
                        sorter: (a, b) => a.metric_names - b.metric_names,
                    },
                    {
                        title: 'Active series',
                        key: 'series',
                        align: 'right',
                        render: (_, service) => humanFriendlyNumber(service.series),
                        sorter: (a, b) => a.series - b.series,
                    },
                    {
                        title: 'Last seen',
                        key: 'last_seen',
                        render: (_, service) => (
                            <span className="flex items-center gap-2">
                                <TZLabel time={service.last_seen} />
                                {isStale(service.last_seen) && <LemonTag type="warning">quiet</LemonTag>}
                            </span>
                        ),
                        sorter: (a, b) => a.last_seen.localeCompare(b.last_seen),
                    },
                ]}
            />
        </div>
    )
}
