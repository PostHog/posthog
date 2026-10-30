import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { TeamMembershipLevel } from 'lib/constants'

import type { InsightLogicProps } from '~/types'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { filterCheckParts } from './dataCheckText'
import { ExcludeFromFilterButton } from './ExcludeFromFilterButton'
import { ExcludeFromInsightButton } from './ExcludeFromInsightButton'
import { FixWithPostHogAIButton } from './FixWithPostHogAIButton'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import { NotCaughtByFilter } from './NotCaughtByFilter'

export function FilterCheckDetails({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
}): JSX.Element {
    const logic = insightDataChecksLogic(insightProps)
    const { filtersTestAccounts, filterRemovesBots, queryFiltersTestAccounts } = useValues(logic)
    const { setFiltersTestAccounts, reportButtonClicked } = useActions(logic)
    const { caught, missed } = filterCheckParts(check, filtersTestAccounts, filterRemovesBots)
    const canEditFilter = !useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <div className="flex w-full flex-col gap-3">
            <div className="flex flex-col items-start gap-1.5">
                {caught && (
                    <Text size="xs" variant="muted">
                        {caught}
                    </Text>
                )}
                <TestAccountFilterSwitch
                    // The insight editor renders this switch too, so a shared id would point its label at the wrong one.
                    id="insight-data-check-test-account-filter"
                    size="small"
                    checked={queryFiltersTestAccounts}
                    onChange={(checked) => {
                        reportButtonClicked(
                            checked ? 'filter_internal_users_on' : 'filter_internal_users_off',
                            check.key
                        )
                        setFiltersTestAccounts(checked, check.key)
                    }}
                    settingsLinkIcon="new-tab"
                    data-attr="insight-data-check-filter-internal-users"
                />
            </div>
            {missed && (
                <div className="flex flex-col items-start gap-3">
                    <NotCaughtByFilter
                        count={missed.count}
                        noun={missed.noun}
                        examples={missed.examples}
                        fallback={missed.fallback}
                        predicate={missed.predicate}
                        explanation={missed.explanation}
                    />
                    <div className="flex flex-wrap gap-2">
                        <ExcludeFromFilterButton
                            insightProps={insightProps}
                            check={check}
                            canEditFilter={canEditFilter}
                        />
                        {/* PostHog AI would change the project's filter, which only admins may change here. */}
                        {canEditFilter ? (
                            <FixWithPostHogAIButton insightProps={insightProps} check={check} />
                        ) : (
                            <ExcludeFromInsightButton insightProps={insightProps} check={check} />
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
