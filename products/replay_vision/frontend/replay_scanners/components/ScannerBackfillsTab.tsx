import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonBanner, LemonButton, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { urls } from 'scenes/urls'

import { DateMappingOption } from '~/types'

import type { BackfillStatusEnumApi, ReplayScannerBackfillApi } from '../../generated/api.schemas'
import { formatCreditCount, formatCredits } from '../../utils/credits'
import { backfillsLogic, isBackfillActive } from '../backfillsLogic'
import { ReplayScannerTab } from '../replayScannerSceneLogic'

const BACKFILL_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    { key: 'Last 7 days', values: ['-7d'] },
    { key: 'Last 30 days', values: ['-30d'] },
    { key: 'Last 90 days', values: ['-90d'] },
]

const BACKFILL_STATUS_TAG: Record<BackfillStatusEnumApi, { label: string; type: LemonTagType }> = {
    running: { label: 'Running', type: 'success' },
    paused_quota: { label: 'Paused (quota)', type: 'warning' },
    completed: { label: 'Completed', type: 'default' },
    cancelled: { label: 'Cancelled', type: 'muted' },
}

/** Convert a DateFilter token (`-30d`, an ISO date, or null) into an ISO instant for the API. */
export function resolveWindowBound(value: string | null, fallback: dayjs.Dayjs): string {
    return ((value && dateStringToDayJs(value)) || fallback).toISOString()
}

export function ScannerBackfillsTab({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = backfillsLogic({ scannerId })
    const {
        backfills,
        backfillsLoading,
        estimate,
        estimateLoading,
        creatingBackfill,
        transitioningIds,
        windowDateFrom,
        windowDateTo,
    } = useValues(logic)
    const { requestEstimate, createBackfill, cancelBackfill, resumeBackfill, setWindowRange } = useActions(logic)

    const activeBackfill = backfills.find(isBackfillActive)
    const overQuota =
        estimate !== null && estimate.credits_remaining !== null && estimate.total_credits > estimate.credits_remaining

    const estimateWindow = (dateFrom: string | null, dateTo: string | null): void => {
        setWindowRange(dateFrom, dateTo)
        requestEstimate(resolveWindowBound(dateFrom, dayjs().subtract(30, 'day')), resolveWindowBound(dateTo, dayjs()))
    }

    const startDisabledReason = activeBackfill
        ? 'This scanner already has an active backfill'
        : !estimate
          ? 'Pick a time range to see the cost first'
          : estimate.total_sessions === 0
            ? 'No eligible sessions in this time range'
            : undefined

    const columns: LemonTableColumns<ReplayScannerBackfillApi> = [
        {
            title: 'Window',
            key: 'window',
            render: (_, backfill) => (
                <span className="whitespace-nowrap">
                    {dayjs(backfill.window_start).format('MMM D, YYYY')} to{' '}
                    {dayjs(backfill.window_end).format('MMM D, YYYY')}
                </span>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, backfill) => (
                <LemonTag type={BACKFILL_STATUS_TAG[backfill.status].type}>
                    {BACKFILL_STATUS_TAG[backfill.status].label}
                </LemonTag>
            ),
        },
        {
            title: 'Progress',
            key: 'progress',
            render: (_, backfill) => {
                const settled = backfill.succeeded_count + backfill.failed_count + backfill.ineligible_count
                return (
                    <Tooltip
                        title={`${backfill.succeeded_count} succeeded, ${backfill.failed_count} failed, ${backfill.ineligible_count} ineligible, ${backfill.in_flight_count} in flight`}
                    >
                        <span>
                            {backfill.dispatched_count.toLocaleString('en-US')} of{' '}
                            {backfill.total_count.toLocaleString('en-US')} dispatched
                            {settled > 0 ? ` (${settled.toLocaleString('en-US')} settled)` : ''}
                        </span>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Spend',
            key: 'spend',
            render: (_, backfill) => (
                <Tooltip title={`At most ${formatCredits(backfill.total_count * backfill.credits_per_observation)}`}>
                    <span>{formatCreditCount(backfill.succeeded_count * backfill.credits_per_observation)}</span>
                </Tooltip>
            ),
        },
        {
            title: 'Created',
            key: 'created',
            render: (_, backfill) => (
                <div className="flex flex-col">
                    <TZLabel time={backfill.created_at} />
                    {backfill.created_by ? (
                        <span className="text-muted text-xs">{backfill.created_by.email}</span>
                    ) : null}
                </div>
            ),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, backfill) => (
                <div className="flex gap-1">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        to={
                            combineUrl(urls.replayVision(scannerId), {
                                tab: ReplayScannerTab.Observations,
                                backfill_id: backfill.id,
                            }).url
                        }
                        data-attr="vision-backfill-view-observations"
                    >
                        View observations
                    </LemonButton>
                    {backfill.status === 'paused_quota' && (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={() => resumeBackfill(backfill.id)}
                            loading={transitioningIds.includes(backfill.id)}
                            data-attr="vision-backfill-resume"
                        >
                            Resume
                        </LemonButton>
                    )}
                    {isBackfillActive(backfill) && (
                        <LemonButton
                            size="xsmall"
                            status="danger"
                            type="secondary"
                            onClick={() => cancelBackfill(backfill.id)}
                            loading={transitioningIds.includes(backfill.id)}
                            data-attr="vision-backfill-cancel"
                        >
                            Cancel
                        </LemonButton>
                    )}
                </div>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="rounded border p-4 flex flex-col gap-3">
                <div>
                    <h3 className="mb-1">Scan historical recordings</h3>
                    <p className="text-muted mb-0">
                        Run this scanner over recordings from before it was created or enabled. Sessions the scanner
                        already observed are skipped and not billed. The backfill uses the scanner's current
                        configuration, frozen when it starts, so later edits don't affect it.
                    </p>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <DateFilter
                        size="small"
                        dateFrom={windowDateFrom}
                        dateTo={windowDateTo}
                        dateOptions={BACKFILL_DATE_OPTIONS}
                        onChange={(dateFrom, dateTo) => estimateWindow(dateFrom, dateTo)}
                        data-attr="vision-backfill-date-filter"
                    />
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => estimate && createBackfill(estimate.window_start, estimate.window_end)}
                        loading={creatingBackfill}
                        disabledReason={startDisabledReason}
                        data-attr="vision-backfill-start"
                    >
                        Start backfill
                    </LemonButton>
                </div>
                {estimateLoading ? (
                    <p className="text-muted mb-0">Counting eligible sessions…</p>
                ) : estimate ? (
                    <div className="flex flex-col gap-2">
                        <p className="mb-0">
                            {estimate.total_sessions.toLocaleString('en-US')}{' '}
                            {estimate.total_sessions === 1 ? 'session' : 'sessions'} will be scanned, costing at most{' '}
                            {formatCredits(estimate.total_credits)}.
                            {estimate.credits_remaining !== null
                                ? ` You have ${formatCreditCount(estimate.credits_remaining)} left this month.`
                                : ''}
                        </p>
                        {overQuota && (
                            <LemonBanner type="warning">
                                This backfill costs more than your remaining monthly credits. It will scan the most
                                recent sessions first, pause when the quota runs out, and you can resume it next period.
                            </LemonBanner>
                        )}
                    </div>
                ) : null}
            </div>

            <LemonTable
                dataSource={backfills}
                columns={columns}
                loading={backfillsLoading}
                rowKey="id"
                emptyState="No backfills yet. Pick a time range above to scan historical recordings."
                data-attr="vision-backfills-table"
            />
        </div>
    )
}
