import { autoDiscoveredOption } from 'lib/components/QuickFilters/quickFilterOptions'

import { ANY_ITEM, STATUS_ITEM, discoveredValuesComboboxItems } from './discoveredValuesComboboxItems'

const web = autoDiscoveredOption('web')
const python = autoDiscoveredOption('posthog-python')

describe('discoveredValuesComboboxItems', () => {
    it.each([
        {
            description: 'offers the clear control first and pins the selection without a search',
            search: '',
            discoveredOptions: [web],
            selectedOptionId: python.id,
            showStatus: false,
            expected: [ANY_ITEM, python.id, web.id],
        },
        {
            description: 'lists only matches while searching, so Enter picks the top match',
            search: 'we',
            discoveredOptions: [web],
            selectedOptionId: python.id,
            showStatus: false,
            expected: [web.id],
        },
        {
            description: 'leaves nothing selectable when a search has no matches',
            search: 'zzz',
            discoveredOptions: [],
            selectedOptionId: python.id,
            showStatus: true,
            expected: [STATUS_ITEM],
        },
    ])('$description', ({ search, discoveredOptions, selectedOptionId, showStatus, expected }) => {
        expect(discoveredValuesComboboxItems({ search, discoveredOptions, selectedOptionId, showStatus })).toEqual(
            expected
        )
    })
})
