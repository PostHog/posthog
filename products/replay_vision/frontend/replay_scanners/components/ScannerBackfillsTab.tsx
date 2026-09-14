import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { urls } from 'scenes/urls'

import { DateMappingOption } from '~/types'

import { VisionDocsLink } from '../../components/DocsLink'
import type { BackfillStatusEnumApi, ReplayScannerBackfillApi } from '../../generated/api.schemas'
import { formatCreditCount, formatCredits } from '../../utils/credits'
import { backfillsLogic, isBackfillActive } from '../backfillsLogic'
import { replayScannerLogic } from '../replayScannerLogic'
import { ReplayScannerTab } from '../replayScannerSceneLogic'
import type { ScannerCreatedBy } from '../types'
import { BackfillCostEstimate } from './BackfillCostEstimate'

// Hour-scale presets matter as much as day-scale ones: a common case is re-scanning the last couple
// of hours after fixing a prompt, not re-scanning a month.
const BACKFILL_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    { key: 'Last 3 hours', values: ['-3h'] },
    { key: 'Last 6 hours', values: ['-6h'] },
    { key: 'Last 24 hours', values: ['-24h'] },
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

/** Raw instant, so two window bounds can be compared at a glance. */
const WINDOW_TIME_FORMAT = { formatDate: 'MMM D, YYYY', formatTime: 'HH:mm' }

/** A full UUID overflows the observations filter row; the leading block still identifies a backfill,
 * and the Backfills table shows the whole id to match against. */
export function shortBackfillId(id: string): string {
    return id.slice(0, 8)
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
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))

    const activeBackfill = backfills.find(isBackfillActive)

    // A capped or disabled scanner holds its running backfill without changing the row's status, so
    // the row itself has to say why nothing is progressing.
    const runningHold = scanner?.limit_reached
        ? {
              label: "Waiting on the scanner's credit limit",
              tooltip:
                  'The backfill is on hold and resumes when the credit limit resets at the start of the next billing period.',
          }
        : scanner && !scanner.enabled
          ? {
                label: 'Waiting on the scanner to be enabled',
                tooltip: 'The backfill is on hold and resumes when the scanner is enabled again.',
            }
          : null

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
            title: 'ID',
            key: 'id',
            render: (_, backfill) => (
                <CopyToClipboardInline explicitValue={backfill.id} description="backfill ID" iconSize="xsmall">
                    <span className="font-mono text-xs">{backfill.id}</span>
                </CopyToClipboardInline>
            ),
        },
        {
            title: 'Start',
            key: 'window_start',
            // `timestampStyle="absolute"` is what suppresses the Today/Yesterday substitution; the
            // format props alone leave it on. A window bound has to read as an exact instant so two
            // rows can be compared, and this keeps TZLabel's timezone-conversion popover.
            render: (_, backfill) => (
                <TZLabel time={backfill.window_start} timestampStyle="absolute" {...WINDOW_TIME_FORMAT} />
            ),
        },
        {
            title: 'End',
            key: 'window_end',
            render: (_, backfill) => (
                <TZLabel time={backfill.window_end} timestampStyle="absolute" {...WINDOW_TIME_FORMAT} />
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, backfill) => (
                <div className="flex items-center gap-1 flex-wrap">
                    <LemonTag type={BACKFILL_STATUS_TAG[backfill.status].type}>
                        {BACKFILL_STATUS_TAG[backfill.status].label}
                    </LemonTag>
                    {backfill.status === 'running' && runningHold && (
                        <Tooltip title={runningHold.tooltip}>
                            <LemonTag type="warning">{runningHold.label}</LemonTag>
                        </Tooltip>
                    )}
                </div>
            ),
        },
        {
            title: 'Progress',
            key: 'progress',
            render: (_, backfill) => {
                const settled = backfill.succeeded_count + backfill.failed_count + backfill.ineligible_count
                const skippedNote = backfill.skipped_count
                    ? `, ${backfill.skipped_count} scanned by the live sweep first`
                    : ''
                // Both count as done: dispatched by this backfill, or taken over by the sweep while it ran.
                const handled = backfill.dispatched_count + backfill.skipped_count
                const nothingToDo = backfill.status === 'completed' && handled === 0
                const progress = nothingToDo
                    ? 'Nothing left to scan'
                    : `${handled.toLocaleString('en-US')} of ${backfill.total_count.toLocaleString(
                          'en-US'
                      )} scanned${settled > 0 ? ` (${settled.toLocaleString('en-US')} settled)` : ''}`
                return (
                    <Tooltip
                        title={`${backfill.succeeded_count} succeeded, ${backfill.failed_count} failed, ${backfill.ineligible_count} ineligible, ${backfill.in_flight_count} in flight${skippedNote}`}
                    >
                        <span className={nothingToDo ? 'text-muted' : undefined}>{progress}</span>
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
            // Relative here, unlike the window bounds: "how long ago was this started" is the useful
            // reading, and it matches how created timestamps show elsewhere in the app.
            render: (_, backfill) => <TZLabel time={backfill.created_at} />,
        },
        {
            title: 'Created by',
            key: 'created_by',
            render: (_, backfill) =>
                backfill.created_by ? (
                    // Same adapter the scanner list uses: the generated hedgehog_config shape does not
                    // match ProfilePicture's, and it is not needed to draw an avatar.
                    <ProfilePicture user={backfill.created_by as ScannerCreatedBy} size="md" showName />
                ) : (
                    <span className="text-secondary">—</span>
                ),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, backfill) => (
                <More
                    data-attr="vision-backfill-actions"
                    overlay={
                        <>
                            <LemonButton
                                fullWidth
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
                                    fullWidth
                                    onClick={() => resumeBackfill(backfill.id)}
                                    disabledReason={transitioningIds.includes(backfill.id) ? 'Resuming…' : undefined}
                                    data-attr="vision-backfill-resume"
                                >
                                    Resume
                                </LemonButton>
                            )}
                            {isBackfillActive(backfill) && (
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    onClick={() => cancelBackfill(backfill.id)}
                                    disabledReason={transitioningIds.includes(backfill.id) ? 'Cancelling…' : undefined}
                                    data-attr="vision-backfill-cancel"
                                >
                                    Cancel
                                </LemonButton>
                            )}
                        </>
                    }
                />
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="rounded border p-4 flex flex-col gap-3">
                <div>
                    <h3 className="mb-1">Scan historical recordings</h3>
                    <p className="text-muted mb-0">
                        Run this scanner over older recordings, including ones from before you created it. The backfill
                        skips recordings it has already scanned, so you're not billed twice. It uses the scanner's
                        settings as they are now, so editing the scanner later won't change a backfill that's already
                        running.
                    </p>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <DateFilter
                        size="small"
                        dateFrom={windowDateFrom}
                        dateTo={windowDateTo}
                        dateOptions={BACKFILL_DATE_OPTIONS}
                        onChange={(dateFrom, dateTo) => estimateWindow(dateFrom, dateTo)}
                        allowTimePrecision
                        allowFixedRangeWithTime
                        allowedRollingDateOptions={['hours', 'days', 'weeks', 'months']}
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
                <BackfillCostEstimate estimate={estimate} loading={estimateLoading} />
            </div>

            <LemonTable
                dataSource={backfills}
                columns={columns}
                loading={backfillsLoading}
                rowKey="id"
                emptyState={
                    <>
                        No backfills yet. Pick a time range above to scan historical recordings.{' '}
                        <VisionDocsLink page="running-scanners" dataAttr="vision-empty-docs-link-backfills">
                            Learn how backfills work
                        </VisionDocsLink>
                    </>
                }
                data-attr="vision-backfills-table"
            />
        </div>
    )
}
