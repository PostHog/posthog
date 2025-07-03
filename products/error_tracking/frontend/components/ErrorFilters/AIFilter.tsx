import { IconKeyboard, IconSparkles } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { MaxTool } from 'scenes/max/MaxTool'
import { userLogic } from 'scenes/userLogic'
import { forwardRef } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { LemonInput, LemonInputPropsText } from 'lib/lemon-ui/LemonInput/LemonInput'
import { TooltipProps } from 'lib/lemon-ui/Tooltip'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'
import { DateRange } from '~/queries/schema/schema-general'

import { errorFiltersLogic } from './errorFiltersLogic'

interface AIFilterOutput {
    search_query?: string | null
    date_range?: {
        date_from?: string
        date_to?: string
    } | null
    filter_test_accounts?: boolean | null
    filter_group?: Record<string, any> | null
}

export const AIEnhancedTaxonomicFilterSearchInput = forwardRef<
    HTMLInputElement,
    {
        searchInputRef: React.Ref<HTMLInputElement> | null
        onClose?: () => void
        selectedIssueIds?: string[]
    } & Pick<LemonInputPropsText, 'onClick' | 'size' | 'prefix' | 'fullWidth' | 'onChange'> &
        Pick<TooltipProps, 'docLink'>
>(function AIEnhancedTaxonomicFilterSearchInput(
    { searchInputRef, onClose, onChange, docLink, selectedIssueIds = [], ...props },
    ref
): JSX.Element {
    const { searchQuery, searchPlaceholder } = useValues(taxonomicFilterLogic)
    const {
        setSearchQuery: setTaxonomicSearchQuery,
        moveUp,
        moveDown,
        tabLeft,
        tabRight,
        selectSelected,
    } = useActions(taxonomicFilterLogic)

    const { dateRange, filterGroup, filterTestAccounts } = useValues(errorFiltersLogic)
    const { setDateRange, setFilterGroup, setFilterTestAccounts, setSearchQuery } = useActions(errorFiltersLogic)
    const { user } = useValues(userLogic)

    const _onChange = (query: string): void => {
        setTaxonomicSearchQuery(query)
        onChange?.(query)
    }

    const handleAIFiltersUpdate = (toolOutput: AIFilterOutput): void => {
        // Update search query
        if (toolOutput.search_query !== undefined) {
            if (toolOutput.search_query === null) {
                setSearchQuery('')
                setTaxonomicSearchQuery('')
                _onChange('')
            } else {
                setSearchQuery(toolOutput.search_query)
                setTaxonomicSearchQuery(toolOutput.search_query)
                _onChange(toolOutput.search_query)
            }
        }

        // Update date range
        if (toolOutput.date_range !== undefined) {
            if (toolOutput.date_range === null) {
                setDateRange({ date_from: '-1d', date_to: null })
            } else {
                const newDateRange: DateRange = {
                    date_from: toolOutput.date_range.date_from || dateRange.date_from,
                    date_to: toolOutput.date_range.date_to || dateRange.date_to,
                }
                setDateRange(newDateRange)
            }
        }

        // Update filter test accounts
        if (toolOutput.filter_test_accounts !== undefined && toolOutput.filter_test_accounts !== null) {
            setFilterTestAccounts(toolOutput.filter_test_accounts)
        }

        // Update property filters
        if (toolOutput.filter_group) {
            const filterGroupData = toolOutput.filter_group as any
            if (filterGroupData.type && filterGroupData.values) {
                const newFilterGroup: UniversalFiltersGroup = {
                    type: filterGroupData.type === 'AND' ? FilterLogicalOperator.And : FilterLogicalOperator.Or,
                    values: filterGroupData.values.map((group: any) => ({
                        type: group.type === 'AND' ? FilterLogicalOperator.And : FilterLogicalOperator.Or,
                        values: group.values || [],
                    })),
                }
                setFilterGroup(newFilterGroup)
            }
        }
    }

    const currentFilters = {
        current_filters: JSON.stringify({
            dateRange,
            filterGroup,
            filterTestAccounts,
            searchQuery,
        }),
        current_user_email: user?.email || '',
        current_user_name: user?.first_name || '',
    }

    // Create suffix with conditional AI capability
    const suffixContent = (
        <div className="flex items-center gap-1">
            {selectedIssueIds.length === 0 && (
                <MaxTool
                    name="create_error_tracking_filters"
                    displayName="AI Search"
                    context={currentFilters}
                    callback={handleAIFiltersUpdate}
                    initialMaxPrompt="Help me find specific error tracking issues"
                >
                    <Tooltip title="Use AI to search and filter issues with natural language">
                        <IconSparkles
                            className="cursor-pointer transition-colors text-secondary hover:text-primary"
                            style={{ fontSize: '1.2rem' }}
                        />
                    </Tooltip>
                </MaxTool>
            )}
            <Tooltip
                title={
                    'Fuzzy text search, or filter by specific properties and values.' +
                    (docLink ? ' Check the documentation for more information.' : '')
                }
                docLink={docLink}
            >
                <IconKeyboard style={{ fontSize: '1.2rem' }} className="text-secondary" />
            </Tooltip>
        </div>
    )

    return (
        <LemonInput
            {...props}
            ref={ref}
            data-attr="taxonomic-filter-searchfield"
            type="search"
            fullWidth
            placeholder={`Search ${searchPlaceholder}`}
            value={searchQuery}
            suffix={suffixContent}
            onKeyDown={(e) => {
                let shouldPreventDefault = true
                switch (e.key) {
                    case 'ArrowUp':
                        moveUp()
                        break
                    case 'ArrowDown':
                        moveDown()
                        break
                    case 'Tab':
                        e.shiftKey ? tabLeft() : tabRight()
                        break
                    case 'Enter':
                        selectSelected()
                        break
                    case 'Escape':
                        _onChange('')
                        onClose?.()
                        break
                    default:
                        shouldPreventDefault = false
                }
                if (shouldPreventDefault) {
                    e.preventDefault()
                }
            }}
            inputRef={searchInputRef}
            onChange={_onChange}
        />
    )
})
