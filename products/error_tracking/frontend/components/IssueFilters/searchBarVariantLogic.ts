import { actions, kea, path, reducers } from 'kea'

import type { searchBarVariantLogicType } from './searchBarVariantLogicType'

export type SearchBarVariant = 'v1' | 'v2'

/**
 * When the redesign flag is enabled the user defaults to the new (v2) filter bar but can flip
 * back to the legacy (v1) layout via the toggle on the bar. The choice is persisted per browser.
 */
export const searchBarVariantLogic = kea<searchBarVariantLogicType>([
    path(['products', 'error_tracking', 'components', 'IssueFilters', 'searchBarVariantLogic']),

    actions({
        setVariant: (variant: SearchBarVariant) => ({ variant }),
        toggleVariant: true,
    }),

    reducers({
        variant: [
            'v2' as SearchBarVariant,
            { persist: true },
            {
                setVariant: (_, { variant }) => variant,
                toggleVariant: (state) => (state === 'v2' ? 'v1' : 'v2'),
            },
        ],
    }),
])
