import { IconKeyboard, IconSparkles } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { MaxTool } from 'scenes/max/MaxTool'
import { userLogic } from 'scenes/userLogic'
import { forwardRef, useState } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { LemonInput, LemonInputPropsText } from 'lib/lemon-ui/LemonInput/LemonInput'
import { TooltipProps } from 'lib/lemon-ui/Tooltip'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'

import { FilterLogicalOperator, PropertyFilterType, UniversalFiltersGroup } from '~/types'
import { DateRange } from '~/queries/schema/schema-general'

import { errorFiltersLogic } from './errorFiltersLogic'

interface AIFilterOutput {
    search_query?: string
    status?: string
    assignee?: {
        id: string
        type: 'user' | 'role'
    }
    date_range?: {
        date_from?: string
        date_to?: string
    }
    filter_test_accounts?: boolean
    filter_group?: Record<string, any>
}

export const AIEnhancedTaxonomicFilterSearchInput = forwardRef<
    HTMLInputElement,
    {
        searchInputRef: React.Ref<HTMLInputElement> | null
        onClose?: () => void
    } & Pick<LemonInputPropsText, 'onClick' | 'size' | 'prefix' | 'fullWidth' | 'onChange'> &
        Pick<TooltipProps, 'docLink'>
>(function AIEnhancedTaxonomicFilterSearchInput(
    { searchInputRef, onClose, onChange, docLink, ...props },
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
    const [isAIMode, setIsAIMode] = useState(false)

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
                onChange?.('')
            } else {
                setSearchQuery(toolOutput.search_query)
                setTaxonomicSearchQuery(toolOutput.search_query)
                onChange?.(toolOutput.search_query)
            }
        }

        // Update date range
        if (toolOutput.date_range !== undefined) {
            if (toolOutput.date_range === null) {
                setDateRange({ date_from: '-7d', date_to: null })
            } else {
                const newDateRange: DateRange = {
                    date_from: toolOutput.date_range.date_from || dateRange.date_from,
                    date_to: toolOutput.date_range.date_to || dateRange.date_to,
                }
                setDateRange(newDateRange)
            }
        }

        // Update filter test accounts
        if (toolOutput.filter_test_accounts !== undefined) {
            setFilterTestAccounts(toolOutput.filter_test_accounts)
        }

        // Update property filters - create a new filter group with the AI-generated filters
        if (toolOutput.status || toolOutput.assignee || toolOutput.filter_group) {
            const newFilters: any[] = []

            // Add status filter
            if (toolOutput.status) {
                newFilters.push({
                    key: 'status',
                    operator: 'exact',
                    value: [toolOutput.status],
                    type: PropertyFilterType.ErrorTrackingIssue,
                })
            }

            // Add assignee filter
            if (toolOutput.assignee) {
                const assigneeId = toolOutput.assignee.id
                const assigneeValue = assigneeId === user?.email ? user?.email || user?.first_name : assigneeId
                newFilters.push({
                    key: 'assignee',
                    operator: 'exact',
                    value: [assigneeValue],
                    type: PropertyFilterType.ErrorTrackingIssue,
                })
            }

            // Handle filter_group (PropertyGroupFilter structure)
            if (toolOutput.filter_group) {
                // If we have a filter_group, use it directly instead of creating newFilters
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
                    setIsAIMode(false)
                    return // Skip the newFilters approach if we have filter_group
                }
            }

            if (newFilters.length > 0) {
                // Create a new filter group with the AI-generated filters
                const newFilterGroup: UniversalFiltersGroup = {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: newFilters,
                        },
                    ],
                }
                setFilterGroup(newFilterGroup)
            }
        }

        // Exit AI mode after applying filters
        setIsAIMode(false)
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

    const suffixContent = (
        <div className="flex items-center gap-1">
            <MaxTool
                name="create_error_tracking_filters"
                displayName="AI Search"
                context={currentFilters}
                callback={handleAIFiltersUpdate}
                initialMaxPrompt="Help me find specific error tracking issues"
                onMaxOpen={() => setIsAIMode(true)}
            >
                <Tooltip title="Use AI to search and filter issues with natural language">
                    <IconSparkles
                        className={`cursor-pointer transition-colors ${
                            isAIMode ? 'text-primary hover:text-primary-dark' : 'text-secondary hover:text-primary'
                        }`}
                        style={{ fontSize: '1.2rem' }}
                        onClick={() => {
                            if (isAIMode) {
                                setIsAIMode(false)
                            } else {
                                setIsAIMode(true)
                            }
                        }}
                    />
                </Tooltip>
            </MaxTool>
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
