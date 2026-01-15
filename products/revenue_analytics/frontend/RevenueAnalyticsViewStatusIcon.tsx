import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCheckCircle, IconClock, IconInfo, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTable, Link, Popover } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

import { DataWarehouseSavedQuery } from '~/types'

import { revenueAnalyticsLogic } from './revenueAnalyticsLogic'

/**
 * Parses a dot-separated view name to extract the group prefix and display name.
 *
 * The group is the one-but-last prefix (all parts except the last one).
 * The display name is the last part.
 *
 * Example:
 *   Input: "revenue_analytics.events.purchase.abc"
 *   Group: "revenue_analytics.events.purchase" (all parts except last)
 *   Display: "abc" (last part)
 */
function parseViewName(name: string): { group: string; displayName: string } {
    const parts = name.split('.')

    if (parts.length <= 1) {
        // Single part or empty, no group
        return { group: '', displayName: name }
    }

    // Group is all parts except the last one
    const group = parts.slice(0, -1).join('.')
    const displayName = parts[parts.length - 1]

    return { group, displayName }
}

type ViewRow = {
    id: string
    name: string
    displayName: string
    group: string
    status: 'success' | 'error' | 'running' | 'paused'
    lastSynced: string | null
    timeSinceLastSync: string | null
    error: string | null
    isPaused: boolean
    view: DataWarehouseSavedQuery
}

const mapError = (error: string): JSX.Element | string => {
    if (error.includes('Query returned no results')) {
        return (
            <span>
                Query returned no results for this view. This either means you haven't{' '}
                <Link
                    to={urls.revenueSettings()}
                    target="_blank"
                    targetBlankIcon={false}
                    className="text-danger underline"
                >
                    configured Revenue Analytics
                </Link>{' '}
                properly (missing subscription properties) or the{' '}
                <Link
                    to={urls.dataPipelines('sources')}
                    target="_blank"
                    targetBlankIcon={false}
                    className="text-danger underline"
                >
                    underlying source of data
                </Link>{' '}
                isn't correctly set-up.
            </span>
        )
    }

    return error
}

export function RevenueAnalyticsViewStatusIcon(): JSX.Element | null {
    const { allRevenueAnalyticsViews, hasRevenueAnalyticsViewsWithIssues, resumingViewSchedule } =
        useValues(revenueAnalyticsLogic)
    const { resumeViewSchedule: resumeSchedule } = useActions(revenueAnalyticsLogic)
    const [isOpen, setIsOpen] = useState(false)
    const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())

    const rows: ViewRow[] = useMemo(() => {
        return allRevenueAnalyticsViews.map((view) => {
            const isPaused = !view.sync_frequency || view.sync_frequency === 'never'
            const hasError = view.status === 'Failed' || view.latest_error
            const isRunning = view.status === 'Running'

            let status: ViewRow['status'] = 'success'
            if (hasError) {
                status = 'error'
            } else if (isRunning) {
                status = 'running'
            } else if (isPaused) {
                status = 'paused'
            }

            const lastSynced = view.last_run_at ? dayjs(view.last_run_at) : null
            const timeSinceLastSync = lastSynced
                ? humanFriendlyDuration(dayjs().diff(lastSynced, 'seconds'), { maxUnits: 2 })
                : null

            const { group, displayName } = parseViewName(view.name)

            return {
                id: view.id,
                name: view.name,
                displayName,
                group,
                status,
                lastSynced: lastSynced ? lastSynced.format('MMM D, YYYY [at] h:mm A') : null,
                timeSinceLastSync,
                error: view.latest_error,
                isPaused,
                view,
            }
        })
    }, [allRevenueAnalyticsViews])

    const groupedRows = useMemo(() => {
        const groups = new Map<string, ViewRow[]>()
        rows.forEach((row) => {
            const groupKey = row.group || 'other'
            if (!groups.has(groupKey)) {
                groups.set(groupKey, [])
            }
            groups.get(groupKey)!.push(row)
        })
        return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
    }, [rows])

    const toggleRowExpansion = (rowId: string): void => {
        setExpandedRows((prev) => {
            const newSet = new Set(prev)
            if (newSet.has(rowId)) {
                newSet.delete(rowId)
            } else {
                newSet.add(rowId)
            }
            return newSet
        })
    }

    if (allRevenueAnalyticsViews.length === 0) {
        return null
    }

    const columns = [
        {
            title: 'View',
            key: 'name',
            render: (_: any, row: ViewRow) => {
                const StatusIcon =
                    row.status === 'error'
                        ? IconWarning
                        : row.status === 'running'
                          ? IconRefresh
                          : row.status === 'paused'
                            ? IconClock
                            : IconCheckCircle

                const iconClassName =
                    row.status === 'error'
                        ? 'text-danger'
                        : row.status === 'running'
                          ? 'text-primary animate-spin'
                          : row.status === 'paused'
                            ? 'text-warning'
                            : 'text-success'

                return (
                    <div className="flex items-center gap-2 min-w-0">
                        <StatusIcon className={`shrink-0 ${iconClassName}`} />
                        <div className="min-w-0 flex-1">
                            <div className="font-medium truncate">{row.displayName}</div>
                        </div>
                    </div>
                )
            },
        },
        {
            title: 'Last synced',
            key: 'lastSynced',
            width: 200,
            align: 'right' as const,
            render: (_: any, row: ViewRow) => {
                if (!row.lastSynced) {
                    return <span className="text-tertiary text-sm">Never</span>
                }
                return (
                    <div className="text-sm text-right">
                        <div>{row.lastSynced}</div>
                        {row.timeSinceLastSync && (
                            <div className="text-tertiary text-xs">{row.timeSinceLastSync} ago</div>
                        )}
                    </div>
                )
            },
        },
        ...(hasRevenueAnalyticsViewsWithIssues
            ? [
                  {
                      title: '',
                      key: 'actions',
                      width: 90,
                      align: 'right' as const,
                      render: (_: any, row: ViewRow) => {
                          if (!row.isPaused) {
                              return null
                          }
                          const isResuming = resumingViewSchedule?.[row.id] || false
                          return (
                              <LemonButton
                                  size="small"
                                  type="secondary"
                                  onClick={() => resumeSchedule(row.id)}
                                  loading={isResuming}
                                  icon={<IconRefresh />}
                              >
                                  Resume
                              </LemonButton>
                          )
                      },
                  },
              ]
            : []),
    ]

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <div className="w-[650px]">
                    <div className="p-3 border-b">
                        <h3 className="font-semibold text-base">Revenue analytics views</h3>
                        <p className="text-sm text-tertiary mt-2">
                            These views are automatically created and synced based on your{' '}
                            <Link
                                to={urls.revenueSettings()}
                                target="_blank"
                                targetBlankIcon={false}
                                className="underline"
                            >
                                Revenue Analytics configuration
                            </Link>
                            . They materialize data from your configured revenue events and external data sources.
                        </p>
                    </div>
                    <div className="max-h-[500px] overflow-y-auto">
                        {groupedRows.map(([group, groupRows]) => (
                            <div key={group} className="mt-2 border-b last:border-b-0">
                                {group && (
                                    <div className="font-mono px-3 py-1.5 bg-bg-light text-xs font-medium text-tertiary border-b">
                                        {group}
                                    </div>
                                )}
                                <LemonTable
                                    dataSource={groupRows}
                                    columns={columns}
                                    embedded
                                    size="small"
                                    rowKey="id"
                                    inset
                                    expandable={{
                                        expandedRowRender: (row: ViewRow) => {
                                            if (!row.error) {
                                                return null
                                            }
                                            return (
                                                <div className="m-2 p-2 bg-danger-highlight rounded text-sm text-danger">
                                                    {mapError(row.error)}
                                                </div>
                                            )
                                        },
                                        rowExpandable: (row: ViewRow) => Boolean(row.error),
                                        isRowExpanded: (row: ViewRow) => (expandedRows.has(row.id) ? 1 : 0),
                                        onRowExpand: (row: ViewRow) => toggleRowExpansion(row.id),
                                        onRowCollapse: (row: ViewRow) => toggleRowExpansion(row.id),
                                    }}
                                />
                            </div>
                        ))}
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type={hasRevenueAnalyticsViewsWithIssues ? 'primary' : 'secondary'}
                icon={hasRevenueAnalyticsViewsWithIssues ? <IconWarning /> : <IconInfo />}
                onClick={() => setIsOpen(!isOpen)}
                tooltip={`View sync status${hasRevenueAnalyticsViewsWithIssues ? ' (problems detected)' : ''}`}
            />
        </Popover>
    )
}
