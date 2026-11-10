import { useActions, useValues } from 'kea'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { QuillTestAccountFilterSwitch } from 'lib/components/QuillTestAccountFilterSwitch'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { InsightQueryNode } from '~/queries/schema/schema-general'

type TestAccountFilterProps = {
    query: InsightQueryNode
    setQuery: (query: InsightQueryNode) => void
    disabledReason?: string
}

export function InsightTestAccountFilter({
    query,
    setQuery,
    disabledReason,
}: TestAccountFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)
    const quillSurface = useQuillSurface()
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const checked = hasFilters ? !!query.filterTestAccounts : false
    const onChange = (checked: boolean): void => {
        setQuery({ ...query, filterTestAccounts: checked })
        setLocalDefault(checked)
    }

    return quillSurface ? (
        <QuillTestAccountFilterSwitch checked={checked} onChange={onChange} disabledReason={disabledReason} />
    ) : (
        <TestAccountFilterSwitch checked={checked} onChange={onChange} disabledReason={disabledReason} />
    )
}
