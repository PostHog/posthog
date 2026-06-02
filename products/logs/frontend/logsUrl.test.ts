import { combineUrl } from 'kea-router'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { DEFAULT_DATE_RANGE } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { getLogsSceneUrl } from './logsUrl'

describe('getLogsSceneUrl', () => {
    const filterGroup = {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        key: 'trace_id',
                        value: ['deadbeef'],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Log,
                    },
                ],
            },
        ],
    }
    const dateRange = { date_from: '2024-01-01T11:55:00.000Z', date_to: '2024-01-01T12:05:00.000Z' }

    it('targets the logs scene', () => {
        expect(combineUrl(getLogsSceneUrl({})).pathname).toEqual('/logs')
    })

    it('encodes non-default filterGroup and dateRange', () => {
        const { searchParams } = combineUrl(getLogsSceneUrl({ filterGroup, dateRange }))
        expect(searchParams.filterGroup).toEqual(filterGroup)
        expect(searchParams.dateRange).toEqual(dateRange)
    })

    it('omits fields not provided', () => {
        const { searchParams } = combineUrl(getLogsSceneUrl({ filterGroup }))
        expect(searchParams.dateRange).toBeUndefined()
        expect(searchParams.serviceNames).toBeUndefined()
    })

    it('omits values equal to their default', () => {
        const { searchParams } = combineUrl(
            getLogsSceneUrl({ dateRange: DEFAULT_DATE_RANGE, filterGroup: DEFAULT_UNIVERSAL_GROUP_FILTER })
        )
        expect(searchParams.dateRange).toBeUndefined()
        expect(searchParams.filterGroup).toBeUndefined()
    })

    it('encodes serviceNames', () => {
        const { searchParams } = combineUrl(getLogsSceneUrl({ serviceNames: ['storefront'] }))
        expect(searchParams.serviceNames).toEqual(['storefront'])
    })
})
