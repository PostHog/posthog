import { connect, events, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { BREAKDOWN_OTHER_DISPLAY } from 'scenes/insights/utils'

import { ErrorTrackingBreakdownsQueryResponse } from '~/queries/schema/schema-general'

import { errorTrackingBreakdownsQuery } from '../../queries'
import { breakdownFiltersLogic } from './breakdownFiltersLogic'
import { BREAKDOWN_PRESETS, BreakdownsEvents, LIMIT_ITEMS } from './consts'
import type { miniBreakdownsLogicType } from './miniBreakdownsLogicType'

export interface MiniBreakdownsLogicProps {
    issueId: string
}

export interface BreakdownSinglePropertyStat {
    label: string
    count: number
}

export const miniBreakdownsLogic = kea<miniBreakdownsLogicType>([
    path(['products', 'error_tracking', 'components', 'Breakdowns', 'miniBreakdownsLogic']),
    props({} as MiniBreakdownsLogicProps),
    key(({ issueId }: MiniBreakdownsLogicProps) => issueId),
    connect(() => ({
        values: [breakdownFiltersLogic, ['dateRange', 'filterTestAccounts']],
    })),
    loaders(({ props, values }) => ({
        response: [
            null as ErrorTrackingBreakdownsQueryResponse | null,
            {
                loadResponse: async () => {
                    const startTime = Date.now()
                    const result = await api.query(
                        errorTrackingBreakdownsQuery({
                            issueId: props.issueId,
                            dateRange: values.dateRange,
                            filterTestAccounts: values.filterTestAccounts,
                            breakdownProperties: BREAKDOWN_PRESETS.map((preset) => preset.property),
                            maxValuesPerProperty: LIMIT_ITEMS,
                        }),
                        { refresh: 'blocking' }
                    )
                    posthog.capture(BreakdownsEvents.MiniBreakdownsLoaded, {
                        issueId: props.issueId,
                        dateRange: values.dateRange,
                        filterTestAccounts: values.filterTestAccounts,
                        breakdownProperties: BREAKDOWN_PRESETS.map((preset) => preset.property),
                        duration: Date.now() - startTime,
                    })

                    return result
                },
            },
        ],
    })),
    selectors(() => ({
        getBreakdownForProperty: [
            (s) => [s.response],
            (response: ErrorTrackingBreakdownsQueryResponse) => {
                return (property: string): { properties: BreakdownSinglePropertyStat[]; totalCount: number } => {
                    const properties: BreakdownSinglePropertyStat[] = []
                    let totalCount = 0

                    if (response && response.results) {
                        if (property && response.results[property]) {
                            const propertyData = response.results[property]

                            propertyData.values.forEach((value: any) => {
                                properties.push({
                                    label: value.value,
                                    count: value.count,
                                })
                            })

                            totalCount = propertyData.total_count || 0

                            const displayedCount = propertyData.values.reduce((sum, value) => sum + value.count, 0)
                            const otherCount = Math.max(0, totalCount - displayedCount)
                            if (otherCount > 0) {
                                properties.push({
                                    label: BREAKDOWN_OTHER_DISPLAY,
                                    count: otherCount,
                                })
                            }
                        }
                    }

                    return { properties, totalCount }
                }
            },
        ],
    })),

    subscriptions(({ actions }) => ({
        dateRange: () => {
            actions.loadResponse()
        },
        filterTestAccounts: () => {
            actions.loadResponse()
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadResponse()
        },
    })),
])
