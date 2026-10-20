import { useActions, useValues } from 'kea'

import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'

import type { InsightLogicProps } from '~/types'

import type { InsightDataCheckKeyEnumApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { insightDataChecksLogic } from './insightDataChecksLogic'

export function FilterTestAccountsSwitch({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckKeyEnumApi
}): JSX.Element {
    const logic = insightDataChecksLogic(insightProps)
    const { queryFiltersTestAccounts } = useValues(logic)
    const { setFiltersTestAccounts } = useActions(logic)
    return (
        <TestAccountFilterSwitch
            // The insight editor renders this switch too, so a shared id would point its label at the wrong one.
            id="insight-data-check-test-account-filter"
            size="small"
            checked={queryFiltersTestAccounts}
            onChange={(checked) => setFiltersTestAccounts(checked, check)}
            settingsLinkIcon="new-tab"
            data-attr="insight-data-check-filter-internal-users"
        />
    )
}
