import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { filterCheckParts } from './dataCheckText'
import { FilterTestAccountsSwitch } from './FilterTestAccountsSwitch'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import { MissedByFilter } from './MissedByFilter'

export function FilterCheckDetails({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
}): JSX.Element {
    const { filtersTestAccounts, filterRemovesBots } = useValues(insightDataChecksLogic(insightProps))
    const parts = filterCheckParts(check, filtersTestAccounts, filterRemovesBots)
    const filterSwitch = <FilterTestAccountsSwitch insightProps={insightProps} check={check.key} />

    return (
        <div className="flex w-full flex-col gap-3">
            {parts.caught ? (
                <div className="flex flex-col items-start gap-1.5">
                    <Text size="xs" variant="muted">
                        {parts.caught}
                    </Text>
                    {filterSwitch}
                </div>
            ) : (
                filterSwitch
            )}
            {parts.missed && <MissedByFilter insightProps={insightProps} check={check} {...parts.missed} />}
        </div>
    )
}
