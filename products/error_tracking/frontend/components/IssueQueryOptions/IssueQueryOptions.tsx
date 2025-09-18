import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'

import { revenueAnalyticsLogic } from 'products/revenue_analytics/frontend/revenueAnalyticsLogic'

import { issuesDataNodeLogic } from '../../logics/issuesDataNodeLogic'
import { ErrorTrackingQueryRevenueEntity, issueQueryOptionsLogic } from './issueQueryOptionsLogic'

const labels = {
    last_seen: 'Last seen',
    first_seen: 'First seen',
    occurrences: 'Occurrences',
    users: 'Users',
    sessions: 'Sessions',
    revenue: 'Revenue',
}

export const IssueQueryOptions = (): JSX.Element => {
    const { groupTypesRaw } = useValues(groupsModel)
    const { orderBy, orderDirection, revenuePeriod } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setRevenueEntity, setOrderDirection, setRevenuePeriod } = useActions(issueQueryOptionsLogic)
    const { hasRevenueTables, hasRevenueEvents } = useValues(revenueAnalyticsLogic)
    const hasRevenueSorting = useFeatureFlag('ERROR_TRACKING_REVENUE_SORTING')

    const hasRevenueAnalytics = hasRevenueTables || hasRevenueEvents

    const onSelectRevenueEntity = (entity: ErrorTrackingQueryRevenueEntity): void => {
        setOrderBy('revenue')
        setRevenueEntity(entity)
    }

    return (
        <span className="flex items-center justify-between gap-2 self-end">
            <Reload />
            <div className="flex items-center gap-2 self-end">
                <div className="flex items-center gap-1">
                    <span>Sort by:</span>

                    <LemonMenu
                        items={[
                            {
                                label: labels['last_seen'],
                                onClick: () => setOrderBy('last_seen'),
                            },
                            {
                                label: labels['first_seen'],
                                onClick: () => setOrderBy('first_seen'),
                            },
                            {
                                label: labels['occurrences'],
                                onClick: () => setOrderBy('occurrences'),
                            },
                            {
                                label: labels['users'],
                                onClick: () => setOrderBy('users'),
                            },
                            {
                                label: labels['sessions'],
                                onClick: () => setOrderBy('sessions'),
                            },
                            hasRevenueSorting && {
                                label: 'Revenue',
                                ...(hasRevenueAnalytics
                                    ? { onClick: () => router.actions.push(urls.revenueSettings()) }
                                    : {
                                          placement: 'right-start',
                                          items: [
                                              {
                                                  label: 'Persons',
                                                  onClick: () => onSelectRevenueEntity('person'),
                                              },
                                              ...groupTypesRaw.map(({ group_type, group_type_index }) => ({
                                                  label: capitalizeFirstLetter(group_type),
                                                  onClick: () => onSelectRevenueEntity(`group_${group_type_index}`),
                                              })),
                                          ],
                                      }),
                            },
                        ]}
                    >
                        <LemonButton size="small" type="secondary">
                            {labels[orderBy]}
                        </LemonButton>
                    </LemonMenu>

                    {orderBy === 'revenue' ? (
                        <LemonSelect
                            onChange={setRevenuePeriod}
                            value={revenuePeriod}
                            options={[
                                {
                                    value: 'last_30_days',
                                    label: 'Last 30 days',
                                },
                                {
                                    value: 'all_time',
                                    label: 'All time',
                                },
                            ]}
                            size="small"
                        />
                    ) : (
                        <LemonSelect
                            onChange={setOrderDirection}
                            value={orderDirection}
                            options={[
                                {
                                    value: 'DESC',
                                    label: 'Descending',
                                },
                                {
                                    value: 'ASC',
                                    label: 'Ascending',
                                },
                            ]}
                            size="small"
                        />
                    )}
                </div>
            </div>
        </span>
    )
}

const Reload = (): JSX.Element => {
    const { responseLoading } = useValues(issuesDataNodeLogic)
    const { reloadData, cancelQuery } = useActions(issuesDataNodeLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    reloadData()
                }
            }}
            icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
        >
            {responseLoading ? 'Cancel' : 'Reload'}
        </LemonButton>
    )
}
