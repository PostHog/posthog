import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTable, Link, Spinner } from '@posthog/lemon-ui'
import { BarChart } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { getColorVar } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { ObservationResultSummary } from '../../components/ObservationCard'
import type { ReplayObservationApi } from '../../generated/api.schemas'
import { ObservationLabelControl } from '../../observations/ObservationLabelControl'
import { fillLabelDays } from '../../utils/labelStats'
import { LABEL_CHART_DAYS, QUALITY_PAGE_SIZE, RatedFilterValue, scannerQualityLogic } from '../scannerQualityLogic'

const RATED_FILTER_OPTIONS: { value: RatedFilterValue; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'unrated', label: 'Unrated' },
    { value: 'rated', label: 'Rated' },
]

function RatingsOverTimePanel({ scannerId }: { scannerId: string }): JSX.Element {
    const { labelStats, labelStatsLoading } = useValues(scannerQualityLogic({ scannerId }))
    const theme = useMemo(() => buildTheme(), [])
    const chart = useMemo(() => (labelStats ? fillLabelDays(labelStats.by_day, LABEL_CHART_DAYS) : null), [labelStats])
    const totalRated = (labelStats?.up_total ?? 0) + (labelStats?.down_total ?? 0)

    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
            <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">Ratings over time</span>
                <span className="text-xs text-muted tabular-nums">
                    {totalRated > 0
                        ? `${labelStats?.up_total ?? 0} thumbs up · ${labelStats?.down_total ?? 0} thumbs down`
                        : `last ${LABEL_CHART_DAYS} days`}
                </span>
            </div>
            {labelStatsLoading && !labelStats ? (
                <div className="flex items-center justify-center py-6 text-muted">
                    <Spinner />
                </div>
            ) : totalRated === 0 || !chart ? (
                <div className="text-muted text-sm">
                    No rated sessions yet. Rate results below to start tracking scanner quality. As the prompt improves,
                    thumbs down should trend down.
                </div>
            ) : (
                <div className="h-48 flex flex-col">
                    <BarChart
                        labels={chart.labels}
                        series={[
                            { key: 'up', label: 'Thumbs up', color: getColorVar('success'), data: chart.up },
                            { key: 'down', label: 'Thumbs down', color: getColorVar('danger'), data: chart.down },
                        ]}
                        config={{ showGrid: false, barLayout: 'stacked' }}
                        theme={theme}
                    />
                </div>
            )}
        </div>
    )
}

/**
 * The scanner's Quality tab: rate results with a thumbs up/down (feedback on thumbs-down), watch quality
 * over time, and hand the rated sessions to PostHog AI to improve the prompt.
 */
export function ScannerQualityTab({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = scannerQualityLogic({ scannerId })
    const { observations, observationsLoading, total, page, ratedFilter } = useValues(logic)
    const { setPage, setRatedFilter, labelChanged } = useActions(logic)

    const columns: LemonTableColumns<ReplayObservationApi> = [
        {
            title: 'Session',
            key: 'session',
            width: 260,
            render: (_, obs) => (
                <Link
                    to={urls.replayVisionObservation(obs.id)}
                    className="font-mono text-xs text-primary truncate block"
                >
                    {obs.session_id}
                </Link>
            ),
        },
        {
            title: 'Result',
            key: 'result',
            render: (_, obs) => (
                <Link to={urls.replayVisionObservation(obs.id)} className="block">
                    <div className="min-w-[16rem] max-w-xl">
                        <ObservationResultSummary observation={obs} />
                    </div>
                </Link>
            ),
        },
        {
            title: 'Scanner got it right?',
            key: 'rating',
            width: 340,
            render: (_, obs) => (
                <ObservationLabelControl
                    compact
                    observationId={obs.id}
                    initialLabel={obs.label}
                    onChange={(label) => labelChanged(obs.id, label)}
                />
            ),
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, obs) => <TZLabel time={obs.created_at} />,
        },
        {
            title: '',
            key: 'actions',
            width: 1,
            render: (_, obs) => (
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRewindPlay />}
                    to={urls.replaySingle(obs.session_id)}
                    className="whitespace-nowrap"
                    data-attr="vision-quality-view-recording"
                >
                    View recording
                </LemonButton>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <p className="text-muted m-0 max-w-2xl">
                Rate scanner results with a thumbs up or down, and add feedback on the ones it got wrong. "Improve
                scanner prompt" then hands your team's ratings to PostHog AI to rewrite the scanner's prompt.
            </p>

            <RatingsOverTimePanel scannerId={scannerId} />

            <div className="space-y-2">
                <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-base m-0">Rate results</h3>
                    <div className="ml-auto">
                        <LemonSegmentedButton
                            size="small"
                            value={ratedFilter}
                            onChange={setRatedFilter}
                            options={RATED_FILTER_OPTIONS}
                            data-attr="vision-quality-rated-filter"
                        />
                    </div>
                </div>
                <LemonTable
                    columns={columns}
                    dataSource={observations}
                    loading={observationsLoading}
                    rowKey="id"
                    pagination={{
                        controlled: true,
                        pageSize: QUALITY_PAGE_SIZE,
                        currentPage: page,
                        entryCount: total,
                        onForward: () => setPage(page + 1),
                        onBackward: () => setPage(page - 1),
                    }}
                    nouns={['observation', 'observations']}
                    emptyState={
                        <div className="p-6 text-center text-muted">
                            {ratedFilter === 'rated'
                                ? 'No rated observations yet. Rate some under "All" or "Unrated".'
                                : ratedFilter === 'unrated'
                                  ? 'No unrated observations. Everything has been rated.'
                                  : "No successful observations to rate yet. They'll appear here once the scanner produces results."}
                        </div>
                    }
                />
            </div>
        </div>
    )
}
