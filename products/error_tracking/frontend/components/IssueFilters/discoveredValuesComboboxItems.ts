import { withSelectedOption } from 'lib/components/QuickFilters/quickFilterOptions'

import { QuickFilterOption } from '~/types'

// Auto-discovered option ids start with '~', so a property value never equals a control id
export const ANY_ITEM = 'control:any'
export const STATUS_ITEM = 'control:status'

export interface DiscoveredValuesComboboxItemsInput {
    search: string
    discoveredOptions: QuickFilterOption[]
    selectedOptionId: string | null
    showStatus: boolean
}

/**
 * The combobox highlights its first item and Enter picks it. While a search runs, the list therefore holds
 * only matches, so Enter selects the top match instead of the "Any" control or the pinned selection.
 */
export function discoveredValuesComboboxItems({
    search,
    discoveredOptions,
    selectedOptionId,
    showStatus,
}: DiscoveredValuesComboboxItemsInput): string[] {
    const options = search ? discoveredOptions : withSelectedOption(discoveredOptions, selectedOptionId)
    return [...(search ? [] : [ANY_ITEM]), ...options.map((option) => option.id), ...(showStatus ? [STATUS_ITEM] : [])]
}
