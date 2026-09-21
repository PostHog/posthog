import { quickFiltersSectionLogic } from 'lib/components/QuickFilters'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { EventPropertyFilter, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    DEFAULT_DATE_RANGE,
    DEFAULT_FILTER_GROUP,
    DEFAULT_SEARCH_QUERY,
    DEFAULT_TEST_ACCOUNT,
    ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY,
    issueFiltersLogic,
} from '../IssueFilters/issueFiltersLogic'
import { issueFilterPreviewLogic } from './issueFilterPreviewLogic'

describe('issueFilterPreviewLogic', () => {
    it('undoes preview filters step by step', () => {
        initKeaTests()
        const filters = issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY })
        const preview = issueFilterPreviewLogic()
        filters.mount()
        preview.mount()

        const firstDateRange = { date_from: '2024-01-01T00:00:00.000Z', date_to: '2024-01-01T02:00:00.000Z' }
        const secondDateRange = { date_from: '2024-01-01T00:00:00.000Z', date_to: '2024-01-01T01:00:00.000Z' }
        preview.actions.applyDateRangeFilter(firstDateRange)
        preview.actions.applyDateRangeFilter(secondDateRange)
        preview.actions.undoActivePreview()
        expect(filters.values.dateRange).toEqual(firstDateRange)
        expect(preview.values.canUndoActivePreview).toBe(true)
        preview.actions.undoActivePreview()
        expect(filters.values.dateRange).toEqual(DEFAULT_DATE_RANGE)
        expect(preview.values.canUndoActivePreview).toBe(false)

        preview.actions.setActivePreview('properties')
        preview.actions.applyPropertyFilter('$browser', 'Chrome')
        const firstFilterGroup = filters.values.filterGroup
        preview.actions.applyPropertyFilter('$browser', 'Chrome')
        expect(filters.values.filterGroup).toEqual(firstFilterGroup)
        expect(preview.values.filterGroupHistory).toHaveLength(1)
        preview.actions.applyPropertyFilter('$os', 'Mac OS X')
        preview.actions.undoActivePreview()
        expect(filters.values.filterGroup).toEqual(firstFilterGroup)
        preview.actions.undoActivePreview()
        expect(filters.values.filterGroup).toEqual(DEFAULT_FILTER_GROUP)

        preview.actions.setActivePreview('fingerprints')
        preview.actions.applyPropertyFilter('$exception_fingerprint', 'fingerprint-1', PropertyOperator.Exact, true)
        preview.actions.applyPropertyFilter('$exception_fingerprint', 'fingerprint-2', PropertyOperator.Exact, true)
        expect(filters.values.filterGroup).toEqual({
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: [
                        {
                            key: '$exception_fingerprint',
                            type: 'event',
                            operator: PropertyOperator.Exact,
                            value: ['fingerprint-2'],
                        },
                    ],
                },
            ],
        })
        expect(preview.values.canUndoActivePreview).toBe(true)
        preview.actions.undoActivePreview()
        expect((filters.values.filterGroup.values[0] as UniversalFiltersGroup).values[0]).toMatchObject({
            key: '$exception_fingerprint',
            value: ['fingerprint-1'],
        })
        preview.actions.undoActivePreview()
        expect(filters.values.filterGroup).toEqual(DEFAULT_FILTER_GROUP)

        preview.unmount()
        filters.unmount()
    })

    it('applies grouped filters as one undo step without opening their chips', () => {
        initKeaTests()
        const filters = issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY })
        const preview = issueFilterPreviewLogic()
        filters.mount()
        preview.mount()
        const chips = (): Partial<EventPropertyFilter>[] =>
            (filters.values.filterGroup.values[0] as UniversalFiltersGroup).values.map((filter) => {
                const { key, value, operator } = filter as EventPropertyFilter
                return { key, value, operator }
            })

        preview.actions.setActivePreview('releases')
        preview.actions.applyPropertyFilter('$browser', 'Chrome')
        const beforeRelease = filters.values.filterGroup
        preview.actions.applyPropertyFilters([
            { key: '$app_version', value: '3.2.0', operator: PropertyOperator.Exact },
            { key: '$app_build', value: null, operator: PropertyOperator.IsNotSet },
        ])
        const afterFirstRelease = filters.values.filterGroup
        expect(chips()).toEqual([
            { key: '$browser', value: ['Chrome'], operator: PropertyOperator.Exact },
            { key: '$app_version', value: ['3.2.0'], operator: PropertyOperator.Exact },
            { key: '$app_build', value: undefined, operator: PropertyOperator.IsNotSet },
        ])
        // FilterGroup opens the popover of every chip it does not count as preview-added.
        expect(filters.values.filterAddedFromPreview).toBe(2)

        // A second release replaces both keys and leaves other chips alone.
        preview.actions.applyPropertyFilters([
            { key: '$app_version', value: '3.3.0', operator: PropertyOperator.Exact },
            { key: '$app_build', value: '20901', operator: PropertyOperator.Exact },
        ])
        expect(chips().map((chip) => chip.key)).toEqual(['$browser', '$app_version', '$app_build'])
        expect(chips()[2]).toEqual({ key: '$app_build', value: ['20901'], operator: PropertyOperator.Exact })
        expect(filters.values.filterAddedFromPreview).toBe(2)
        const afterSecondRelease = filters.values.filterGroup

        // Clearing one key from the preview removes only that chip and stays undoable.
        preview.actions.clearPropertyFilter('$app_build')
        expect(chips().map((chip) => chip.key)).toEqual(['$browser', '$app_version'])
        preview.actions.clearPropertyFilter('$app_build')
        expect(preview.values.filterGroupHistory).toHaveLength(4)

        preview.actions.undoActivePreview()
        expect(filters.values.filterGroup).toEqual(afterSecondRelease)
        preview.actions.undoActivePreview()
        expect(filters.values.filterGroup).toEqual(afterFirstRelease)
        preview.actions.undoActivePreview()
        expect(filters.values.filterGroup).toEqual(beforeRelease)

        preview.unmount()
        filters.unmount()
    })

    it('drops the undo stack when a filter changes manually after a preview', () => {
        initKeaTests()
        const filters = issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY })
        const preview = issueFilterPreviewLogic()
        filters.mount()
        preview.mount()

        // Time preview followed by a manual date change must not be undoable back to the pre-preview range.
        preview.actions.applyDateRangeFilter({
            date_from: '2024-01-01T00:00:00.000Z',
            date_to: '2024-01-01T01:00:00.000Z',
        })
        const manualDateRange = { date_from: '-30d', date_to: null }
        filters.actions.setDateRange(manualDateRange)
        expect(preview.values.dateRangeHistory).toEqual([])
        expect(preview.values.canUndoActivePreview).toBe(false)
        preview.actions.undoActivePreview()
        expect(filters.values.dateRange).toEqual(manualDateRange)

        // Property preview followed by a manual filter edit must not be undoable back to the pre-preview group.
        preview.actions.setActivePreview('properties')
        preview.actions.applyPropertyFilter('$browser', 'Chrome')
        const manualFilterGroup = filters.values.filterGroup
        filters.actions.setFilterGroup(manualFilterGroup)
        expect(preview.values.filterGroupHistory).toEqual([])
        expect(preview.values.canUndoActivePreview).toBe(false)
        preview.actions.undoActivePreview()
        expect(filters.values.filterGroup).toEqual(manualFilterGroup)

        preview.unmount()
        filters.unmount()
    })

    it('clears non-date filters without changing the date range', () => {
        initKeaTests()
        const filters = issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY })
        const quickFilters = quickFiltersSectionLogic({
            context: QuickFilterContext.ErrorTrackingIssueFilters,
            logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY,
        })
        const preview = issueFilterPreviewLogic()
        filters.mount()
        quickFilters.mount()
        preview.mount()

        const dateRange = { date_from: '-30d', date_to: null }
        filters.actions.setDateRange(dateRange)
        preview.actions.applyPropertyFilter('$browser', 'Chrome')
        filters.actions.setFilterTestAccounts(true)
        filters.actions.setSearchQuery('checkout')
        quickFilters.actions.setQuickFilterValue('environment', '$environment', {
            id: 'production',
            label: 'Production',
            value: 'production',
            operator: PropertyOperator.Exact,
        })

        expect(preview.values.hasActiveFilters).toBe(true)
        preview.actions.clearNonDateFilters()

        expect(filters.values.dateRange).toEqual(dateRange)
        expect(filters.values.filterGroup).toEqual(DEFAULT_FILTER_GROUP)
        expect(filters.values.filterTestAccounts).toBe(DEFAULT_TEST_ACCOUNT)
        expect(filters.values.searchQuery).toBe(DEFAULT_SEARCH_QUERY)
        expect(quickFilters.values.selectedQuickFilters).toEqual({})
        expect(preview.values.hasActiveFilters).toBe(false)

        preview.unmount()
        quickFilters.unmount()
        filters.unmount()
    })
})
