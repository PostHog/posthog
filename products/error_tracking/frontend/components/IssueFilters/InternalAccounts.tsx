import { useActions, useValues } from 'kea'

import { InternalAccountsToggle } from '../InternalAccountsToggle'
import { issueFiltersLogic } from './issueFiltersLogic'

export const InternalAccountsFilter = (): JSX.Element => {
    const { filterTestAccounts } = useValues(issueFiltersLogic)
    const { setFilterTestAccounts } = useActions(issueFiltersLogic)

    return <InternalAccountsToggle filterTestAccounts={filterTestAccounts} onChange={setFilterTestAccounts} />
}
