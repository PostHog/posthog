import { useActions, useValues } from 'kea'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { errorFiltersLogic } from './errorFiltersLogic'

export const InternalAccountsFilter = (): JSX.Element => {
    const { filterTestAccounts } = useValues(errorFiltersLogic)
    const { setFilterTestAccounts } = useActions(errorFiltersLogic)

    return (
        <div>
            <TestAccountFilter
                size="small"
                filters={{ filter_test_accounts: filterTestAccounts }}
                onChange={({ filter_test_accounts }) => setFilterTestAccounts(filter_test_accounts || false)}
            />
        </div>
    )
}
